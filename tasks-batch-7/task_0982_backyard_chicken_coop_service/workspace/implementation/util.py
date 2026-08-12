"""Shared utilities: time parsing/formatting, Decimal rounding, calendar math."""
import re
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from errors import fail

ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_TIME_RANGE = "ERR_INVALID_TIME_RANGE"


def now_wall():
    """Wall-clock timestamp for meta.api_request_timestamp only."""
    return datetime.now(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string to an aware UTC datetime; None on failure.

    Accepts a trailing Z and date-only strings (treated as UTC midnight).
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def midnight(dt):
    return dt.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def dec(v):
    """Decimal from an int/float without float artifacts."""
    return Decimal(str(v))


def rhu(x):
    """Round half up to whole integer cents."""
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_months(dt, months=1):
    """Calendar-month addition, clamping the day to the target month's length."""
    idx = dt.month - 1 + months
    y = dt.year + idx // 12
    m = idx % 12 + 1
    d = min(dt.day, monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


_MD_RE = re.compile(r"^(\d{2})-(\d{2})$")
_HM_RE = re.compile(r"^(\d{2}):(\d{2})$")
# Leap-year month lengths so 02-29 is considered well-formed.
_MDAYS = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def valid_md(s):
    if not isinstance(s, str):
        return False
    m = _MD_RE.match(s)
    if not m:
        return False
    mo, d = int(m.group(1)), int(m.group(2))
    return 1 <= mo <= 12 and 1 <= d <= _MDAYS[mo]


def valid_hm(s):
    if not isinstance(s, str):
        return False
    m = _HM_RE.match(s)
    if not m:
        return False
    h, mi = int(m.group(1)), int(m.group(2))
    return 0 <= h <= 23 and 0 <= mi <= 59


def md_ordinal(s):
    """Day-of-year index (0-based) of an MM-DD string in a leap reference year."""
    mo, d = int(s[:2]), int(s[3:5])
    days = 0
    for mth in range(1, mo):
        days += _MDAYS[mth]
    return days + (d - 1)


def md_of(dt):
    return dt.strftime("%m-%d")


# ---------------------------------------------------------------------------
# Request payload helpers
# ---------------------------------------------------------------------------

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str) or not v.strip():
        fail(ERR_INVALID_REQUEST, f"Field '{name}' is required and must be a non-empty string")
    return v


def req_int(data, name):
    v = data.get(name)
    if not is_int(v):
        fail(ERR_INVALID_REQUEST, f"Field '{name}' is required and must be an integer")
    return v


def req_nonneg_int(data, name):
    v = req_int(data, name)
    if v < 0:
        fail(ERR_INVALID_REQUEST, f"Field '{name}' must be >= 0")
    return v


def req_pct(data, name):
    v = data.get(name)
    if not is_num(v):
        fail(ERR_INVALID_REQUEST, f"Field '{name}' is required and must be a number in [0, 1]")
    if v < 0 or v > 1:
        fail(ERR_INVALID_REQUEST, f"Field '{name}' must be a fraction between 0 and 1")
    return v


def req_enum(data, name, allowed):
    v = data.get(name)
    if not isinstance(v, str) or v not in allowed:
        fail(ERR_INVALID_REQUEST, f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def req_dt(data, name):
    v = data.get(name)
    dt = parse_dt(v)
    if dt is None:
        fail(ERR_INVALID_REQUEST, f"Field '{name}' is required and must be an ISO 8601 datetime")
    return dt


def buffered_conflict(ws, we, s, e, buffer_minutes=30):
    """Half-open window conflict with a travel buffer on both sides.

    Conflict iff NOT (ws >= e + buffer OR we <= s - buffer).
    Touching at exactly the buffer mark is allowed.
    """
    buf = timedelta(minutes=buffer_minutes)
    return not (ws >= e + buf or we <= s - buf)
