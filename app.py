import os
import json
import sqlite3
from datetime import datetime, timedelta
import streamlit as st
from groq import Groq

# تنظیمات صفحه Streamlit
st.set_page_title_config = st.set_page_config(page_title="دستیار مهندسی فرآیند", page_icon="⚙️", layout="wide")

# خواندن امن کلید از تنظیمات سرور یا سیستم محلی
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "کد_کلید_گروق_شما")
client = Groq(api_key=GROQ_API_KEY)


# -------------------------------------------------------------
# بخش پایگاه داده (SQLite) برای ذخیره چت‌ها و گزارش‌ها با انقضای ۷ روز
# -------------------------------------------------------------
def init_db():
    conn = sqlite3.connect("engineering_agent.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            timestamp TEXT,
            user_message TEXT,
            agent_response TEXT,
            tool_used TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_chat(user_id, user_msg, agent_resp, tool_name):
    init_db()
    conn = sqlite3.connect("engineering_agent.db")
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO chats (user_id, timestamp, user_message, agent_response, tool_used)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, now, user_msg, agent_resp, tool_name))
    
    # حذف پیام‌های قدیمی‌تر از ۷ روز
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("DELETE FROM chats WHERE timestamp < ?", (week_ago,))
    
    conn.commit()
    conn.close()

# -------------------------------------------------------------
# تعریف ابزار محاسباتی کمپرسور
# -------------------------------------------------------------
def calculate_compression_ratio(p_suction: float, p_discharge: float) -> str:
    if p_suction <= 0:
        return "خطا: فشار ورودی باید بزرگتر از صفر باشد."
    ratio = p_discharge / p_suction
    return json.dumps({
        "p_suction": p_suction,
        "p_discharge": p_discharge,
        "compression_ratio": round(ratio, 2)
    }, ensure_ascii=False)

tools = [
    {
        "type": "function",
        "function": {
            "name": "calculate_compression_ratio",
            "description": "محاسبه نسبت تراکم (Pressure Ratio) کمپرسور از روی فشار ورودی و خروجی",
            "parameters": {
                "type": "object",
                "properties": {
                    "p_suction": {"type": "number", "description": "فشار ورودی یا مکش (بار)"},
                    "p_discharge": {"type": "number", "description": "فشار خروجی یا رانش (بار)"}
                },
                "required": ["p_suction", "p_discharge"]
            }
        }
    }
]

# -------------------------------------------------------------
# رابط کاربری وب با Streamlit
# -------------------------------------------------------------
st.title("⚙️ دستیار هوشمند مهندسی فرآیند و تجهیزات دوار")
st.write("خوش آمدید! سوالات فنی خود را بپرسید یا محاسبات کمپرسور را انجام دهید.")

# شناسایی ساده کاربر (برای تفکیک در دیتابیس)
if "user_id" not in st.session_state:
    st.session_state.user_id = "user_" + datetime.now().strftime("%H%M%S")

# منوی کناری (Sidebar) برای مدیریت و گزارش‌گیری ادمین/کاربر
menu = st.sidebar.selectbox("منو", ["چت با ایجنت", "گزارش مکالمات (من)"])

init_db()

if menu == "چت با ایجنت":
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "system", "content": "تو یک دستیار هوشمند مهندسی فرآیند و تجهیزات دوار هستی. به زبان فارسی روان پاسخ بده. در صورت نیاز به محاسبه نسبت تراکم کمپرسور، حتماً از ابزار calculate_compression_ratio استفاده کن."}
        ]

    # نمایش تاریخچه پیام‌ها در صفحه
    for msg in st.session_state.messages:
        if msg["role"] != "system":
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # دریافت ورودی از کاربر
    if user_input := st.chat_input("سوال فنی خود را اینجا بنویسید..."):
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("در حال پردازش..."):
                try:
                    response = client.chat.completions.create(
                        model="openai/gpt-oss-20b",
                        messages=st.session_state.messages,
                        tools=tools,
                        tool_choice="auto"
                    )
                    
                    response_message = response.choices[0].message
                    tool_calls = response_message.tool_calls
                    tool_used_name = "ندارد"

                    if tool_calls:
                        st.session_state.messages.append(response_message)
                        for tool_call in tool_calls:
                            function_name = tool_call.function.name
                            tool_used_name = function_name
                            function_args = json.loads(tool_call.function.arguments)
                            
                            if function_name == "calculate_compression_ratio":
                                tool_result = calculate_compression_ratio(
                                    p_suction=function_args.get("p_suction"),
                                    p_discharge=function_args.get("p_discharge")
                                )
                                st.session_state.messages.append({
                                    "tool_call_id": tool_call.id,
                                    "role": "tool",
                                    "name": function_name,
                                    "content": tool_result
                                })

                        second_response = client.chat.completions.create(
                            model="openai/gpt-oss-20b",
                            messages=st.session_state.messages
                        )
                        final_reply = second_response.choices[0].message.content
                    else:
                        final_reply = response_message.content

                    st.markdown(final_reply)
                    st.session_state.messages.append({"role": "assistant", "content": final_reply})
                    
                    # ذخیره در دیتابیس (نگهداری ۷ روزه)
                    save_chat(st.session_state.user_id, user_input, final_reply, tool_used_name)

                except Exception as e:
                    st.error(f"خطا در ارتباط با مدل: {str(e)}")

elif menu == "گزارش مکالمات (من)":
    st.subheader("📊 گزارش مکالمات و پرسش‌های شما")
    conn = sqlite3.connect("engineering_agent.db")
    import pandas as pd
    df = pd.read_sql_query(f"SELECT timestamp, user_message, agent_response, tool_used FROM chats WHERE user_id = '{st.session_state.user_id}' ORDER BY id DESC", conn)
    conn.close()
    
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        # امکان دانلود گزارش به صورت CSV
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 دانلود گزارش مکالمات (CSV)",
            data=csv,
            file_name='my_engineering_chat_report.csv',
            mime='text/csv',
        )
    else:
        st.info("هنوز مکالمه‌ای ثبت نشده است.")
