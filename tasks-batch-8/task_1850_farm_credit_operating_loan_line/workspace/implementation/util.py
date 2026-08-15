"""Utilities: ids, time parsing/formatting, request-body shape validation."""
import random
import string
import uuid
from calendar import monthrange
from datetime import date, datetime, timezone

from flask import request

from errors import raise_err


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def wall_ts3():
    """Wall-clock timestamp with three fractional digits (for meta only)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (now.microsecond // 1000)) + "Z"


def parse_dt(value):
    """Parse an ISO-8601 datetime (accepts trailing Z, offsets, date-only)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Compact ISO-8601 UTC: fractional seconds only when nonzero."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return base + "." + ("%06d" % dt.microsecond).rstrip("0") + "Z"
    return base + "Z"


def fmt_ts3(dt):
    """ISO-8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def fmt_date(d):
    return d.isoformat()


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + years, day=28)


def add_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) + months
    y, m0 = divmod(total, 12)
    m = m0 + 1
    d = min(dt.day, monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Request body / shape validation helpers (tier 4: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def need(b, field):
    if field not in b or b[field] is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return b[field]


def as_str(v, field):
    if not isinstance(v, str) or v == "":
        raise_err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return v


def as_int(v, field, min_value=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if min_value is not None and v < min_value:
        raise_err("ERR_INVALID_REQUEST", "Field %s must be >= %d" % (field, min_value))
    return v


def as_pos_int(v, field):
    return as_int(v, field, min_value=1)


def as_nonneg_int(v, field):
    return as_int(v, field, min_value=0)


def as_bool(v, field):
    if not isinstance(v, bool):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return v


def as_enum(v, field, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise_err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s" % (field, ", ".join(allowed)))
    return v


def as_dt(v, field):
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be an ISO-8601 datetime" % field)
    try:
        return parse_dt(v)
    except Exception:
        raise_err("ERR_INVALID_REQUEST", "Field %s must be an ISO-8601 datetime" % field)


def as_str_list(v, field):
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be a list of strings" % field)
    return v


def opt_int(b, field, default, min_value=None):
    if field not in b or b[field] is None:
        return default
    return as_int(b[field], field, min_value=min_value)


def opt_str(b, field):
    v = b.get(field)
    if v is None:
        return None
    return as_str(v, field)
