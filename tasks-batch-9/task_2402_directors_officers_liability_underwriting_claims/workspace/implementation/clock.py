"""The logical clock (PRD 2.4) and ISO 8601 helpers.

The clock is the system's only source of time. Before any operator sets it, it
reads exactly 2026-08-01T00:00:00Z - a fixed startup default that never falls
back to real wall-clock time.
"""

import re
from datetime import datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT_NOW


def now():
    return _now


def set_now(value):
    global _now
    _now = value
    return _now


def reset():
    global _now
    _now = DEFAULT_NOW


_FULL = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _FULL.match(value.strip())
    if not m:
        raise ValueError("not an ISO 8601 instant")
    year, month, day, hour, minute, second, frac, offset = m.groups()
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    dt = datetime(
        int(year),
        int(month),
        int(day),
        int(hour or 0),
        int(minute or 0),
        int(second or 0),
        micro,
        tzinfo=timezone.utc,
    )
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if value is None:
        return None
    dt = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def plus_days(value, days):
    return value + timedelta(days=days)


def whole_days_between(start, end):
    """Whole days from start to end, discarding any part-day (may be negative)."""
    seconds = (end - start).total_seconds()
    return int(seconds // 86400)
