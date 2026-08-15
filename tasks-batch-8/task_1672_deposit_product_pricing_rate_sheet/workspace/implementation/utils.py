"""Shared helpers: ids, timestamps, dates, rounding, validation primitives."""

import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import now_dt
from errors import bad_request


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    return fmt_ts(now_dt())


def today_iso():
    return now_dt().date().isoformat()


def parse_date(s):
    """Parse an ISO calendar-date string; return date or None."""
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_datetime_val(s):
    """Parse an ISO 8601 datetime (or date) string; return aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    try:
        if "T" not in txt and " " not in txt:
            d = date.fromisoformat(txt)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00").replace("z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def add_days_iso(date_str, days):
    d = date.fromisoformat(date_str) if isinstance(date_str, str) else date_str
    return (d + timedelta(days=days)).isoformat()


def round_half_up_int(numer, denom):
    """round_half_up(numer / denom) to integer using Decimal."""
    if denom == 0:
        return 0
    q = (Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def stamp_new(row):
    ts = now_ts()
    row["id"] = new_id()
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    return row


def bump(row):
    row["version"] += 1
    row["updated_at"] = now_ts()


# ---------------------------------------------------------------------------
# Request-body field validators (schema failures -> ERR_INVALID_REQUEST 400)
# ---------------------------------------------------------------------------

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_field(data, field):
    if field not in data or data[field] is None:
        raise bad_request(f"Missing required field: {field}")
    return data[field]


def req_str(data, field):
    v = req_field(data, field)
    if not isinstance(v, str) or v == "":
        raise bad_request(f"Field {field} must be a non-empty string")
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise bad_request(f"Field {field} must be a string")
    return v


def req_int(data, field, minimum=None):
    v = req_field(data, field)
    if not _is_int(v):
        raise bad_request(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise bad_request(f"Field {field} must be >= {minimum}")
    return v


def opt_int(data, field, default=None, minimum=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not _is_int(v):
        raise bad_request(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise bad_request(f"Field {field} must be >= {minimum}")
    return v


def req_bool(data, field):
    v = req_field(data, field)
    if not isinstance(v, bool):
        raise bad_request(f"Field {field} must be a boolean")
    return v


def req_date(data, field):
    v = req_field(data, field)
    d = parse_date(v)
    if d is None:
        raise bad_request(f"Field {field} must be an ISO date string")
    return v


def opt_date(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if parse_date(v) is None:
        raise bad_request(f"Field {field} must be an ISO date string")
    return v


def req_enum(data, field, allowed):
    v = req_field(data, field)
    if v not in allowed:
        raise bad_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_list(data, field, allow_empty=True):
    v = req_field(data, field)
    if not isinstance(v, list):
        raise bad_request(f"Field {field} must be an array")
    if not allow_empty and len(v) == 0:
        raise bad_request(f"Field {field} must not be empty")
    return v
