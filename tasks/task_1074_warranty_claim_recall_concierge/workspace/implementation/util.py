"""Low-level utilities: id generation, datetime parse/format. No store imports."""
import random
import string
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def gen_req_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def now_iso():
    return format_dt(datetime.now(timezone.utc))


def format_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(s):
    if isinstance(s, datetime):
        dt = s
    else:
        t = str(s).strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def last_day_of_month(year, month):
    if month == 12:
        nxt_y, nxt_m = year + 1, 1
    else:
        nxt_y, nxt_m = year, month + 1
    from datetime import date, timedelta
    return (date(nxt_y, nxt_m, 1) - timedelta(days=1)).day


def add_calendar_months(dt, months):
    """Advance dt by `months` calendar months; clamp overflow to last day of month."""
    total = (dt.month - 1) + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, last_day_of_month(year, month))
    return dt.replace(year=year, month=month, day=day)
