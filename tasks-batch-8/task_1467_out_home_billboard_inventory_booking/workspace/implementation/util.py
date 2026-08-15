"""Shared utilities: logical clock, timestamps, dates, decimal rounding."""
import re
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5). Starts at exactly 2026-08-01T00:00:00Z.
# ---------------------------------------------------------------------------
_CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _CLOCK["now"]


def clock_today():
    return _CLOCK["now"].date()


def set_clock(dt):
    _CLOCK["now"] = dt


# ---------------------------------------------------------------------------
# Timestamp formatting. Resource timestamps: ISO 8601 UTC, 3 fractional digits.
# ---------------------------------------------------------------------------
def ts3(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def ts_clock(dt):
    """Clock echo: no fraction when whole seconds, else milliseconds."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return ts3(dt)


def wall_ts():
    return ts3(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s, field):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be a date string YYYY-MM-DD" % field)
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' is not a valid calendar date" % field)


def parse_dt(s, field):
    if not isinstance(s, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be an ISO 8601 datetime string" % field)
    txt = s.strip()
    try:
        if txt.endswith("Z"):
            dt = datetime.fromisoformat(txt[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(txt)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' is not a parseable ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def midnight_of(d):
    return datetime.combine(d, time(0, 0, 0), tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Decimal / rounding discipline (PRD 2.6): integer cents, round half-up.
# ---------------------------------------------------------------------------
def D(x):
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise ValueError("bool is not numeric")
    return Decimal(str(x))


def rhu(value):
    """Round half-up to integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_places(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def ceil_div(a, b):
    return -(-a // b)


# ---------------------------------------------------------------------------
# JSON field type guards
# ---------------------------------------------------------------------------
def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_int(body, field, minimum=None):
    v = body.get(field)
    if not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' is required and must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be >= %s" % (field, minimum))
    return v


def opt_int(body, field, minimum=None):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be >= %s" % (field, minimum))
    return v


def req_num(body, field, minimum=None):
    v = body.get(field)
    if not is_num(v):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' is required and must be a number" % field)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be >= %s" % (field, minimum))
    return v


def opt_num(body, field, minimum=None):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not is_num(v):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be a number" % field)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be >= %s" % (field, minimum))
    return v


def req_str(body, field, allow_empty=False):
    v = body.get(field)
    if not isinstance(v, str) or (not allow_empty and v == ""):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' is required and must be a string" % field)
    return v


def opt_str(body, field, default=None, allow_empty=True):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or (not allow_empty and v == ""):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be a string" % field)
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' is required and must be a boolean" % field)
    return v


def opt_bool(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be a boolean" % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v
