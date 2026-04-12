import uuid
from datetime import datetime, timezone


def gen_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc_now():
    return datetime.now(timezone.utc)


# In-memory stores
rooms = {}
bookings = {}
series = {}
waitlist = {}
audit_logs = {}
