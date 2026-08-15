"""Shared helpers: ids, timestamps, logical clock access, decimal rounding,
date parsing, and primitive type validators."""
import uuid
from datetime import date, datetime, timezone

from db import clock, next_seq

VALID_ROLES = {
    "LibraryAdmin",
    "LibraryClerk",
    "ReturnsClerk",
    "BillingManager",
    "RightsAdvisor",
    "Customer",
}


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def now_dt():
    return clock["now"]


def now_date():
    return clock["now"].date()


def fmt_ts3(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_ts0(dt):
    """ISO 8601 UTC, second precision, e.g. 2026-08-01T00:00:00Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_instant(s):
    """Parse an ISO 8601 date or datetime into an aware UTC datetime; None if bad."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    try:
        if "T" in t or " " in t:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        d = date.fromisoformat(t)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_day(s):
    """Parse an ISO 8601 date/datetime to a date (day granularity); None if bad."""
    dt = parse_instant(s)
    return dt.date() if dt is not None else None


def new_record():
    ts = now_dt()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    rec["updated_at"] = now_dt()
    rec["version"] += 1


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_bool(x):
    return isinstance(x, bool)


def is_str(x):
    return isinstance(x, str) and len(x) > 0
