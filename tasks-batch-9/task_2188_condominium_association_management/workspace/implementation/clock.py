"""Logical clock. All temporal reasoning reads this, never wall-clock time."""
import re
from datetime import datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt


def reset():
    _state["now"] = DEFAULT_NOW


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6}))?)?"
    r"\s*(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse(value):
    """Parse an ISO 8601 datetime or plain date string.  Returns None if unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        dt = datetime(
            int(y), int(mo), int(d),
            int(hh) if hh else 0,
            int(mm) if mm else 0,
            int(ss) if ss else 0,
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def add_days(dt, days):
    return dt + timedelta(days=days)


def floor_days(later, earlier):
    """Whole-day count of (later - earlier), floored toward negative infinity.

    timedelta normalizes so that seconds/microseconds are always non-negative
    and `days` is therefore already the floor of the day count.
    """
    return (later - earlier).days
