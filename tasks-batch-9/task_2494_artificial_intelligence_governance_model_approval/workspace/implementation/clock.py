"""Server-side logical clock (PRD 2.3).

Every timestamp the server writes and every deadline comparison reads this
clock, never the host wall clock.  The clock starts at 2026-08-01T00:00:00Z on
each fresh boot and only moves when POST /_clock/set_current_utc says so.
"""
from datetime import datetime, timedelta, timezone

INITIAL_CURRENT_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current_utc = INITIAL_CURRENT_UTC


def now():
    return _current_utc


def set_now(value):
    global _current_utc
    _current_utc = value.astimezone(timezone.utc)
    return _current_utc


def reset():
    global _current_utc
    _current_utc = INITIAL_CURRENT_UTC


def iso(value):
    """ISO 8601 UTC with exactly three fractional-second digits and a Z suffix."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def plus_days(value, days):
    return value + timedelta(days=days)


def plus_hours(value, hours):
    return value + timedelta(hours=hours)
