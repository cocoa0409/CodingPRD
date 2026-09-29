"""Logical clock (PRD 2.4).

Server-stamped time never comes from the wall clock. The clock starts at
2026-08-01T00:00:00Z and only POST /_clock/set_current_utc moves it.
"""
from datetime import datetime, timedelta, timezone

INITIAL = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock(object):
    def __init__(self):
        self.current = INITIAL

    def reset(self):
        self.current = INITIAL


clock = _Clock()


def now():
    return clock.current


def set_now(dt):
    clock.current = dt


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now_fmt():
    return fmt(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse a client-supplied ISO 8601 instant. Returns None when unparsable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def plus_days(dt, days):
    return dt + timedelta(days=days)


def day_bucket(dt):
    """UTC calendar date of an instant."""
    return dt.astimezone(timezone.utc).date()
