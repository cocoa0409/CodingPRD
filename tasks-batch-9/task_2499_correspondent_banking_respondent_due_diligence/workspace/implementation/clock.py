"""The server-held logical clock plus ISO-8601 helpers (PRD 2.5, 2.4)."""

import re
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_state = {"now": DEFAULT_CLOCK}


def now():
    """Current logical-clock instant."""
    return _state["now"]


def set_now(dt):
    _state["now"] = dt
    return dt


def reset():
    _state["now"] = DEFAULT_CLOCK


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_iso():
    return iso(datetime.now(tz=UTC))


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_instant(value):
    """Parse an ISO 8601 date or instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offs = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offs
    return base


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(value):
    """Parse a YYYY-MM string into a (year, month) tuple, or None."""
    if not isinstance(value, str):
        return None
    m = _MONTH_RE.match(value.strip())
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if month < 1 or month > 12:
        return None
    return (year, month)


def _last_day(year, month):
    if month == 12:
        return 31
    nxt = datetime(year, month + 1, 1, tzinfo=UTC)
    return (nxt - timedelta(days=1)).day


def add_months(dt, months):
    """Add whole months, preserving day-of-month and time; clamp short months."""
    if months == 0:
        return dt
    total = (dt.year * 12 + (dt.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, _last_day(year, month))
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    return dt + timedelta(hours=24 * days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)
