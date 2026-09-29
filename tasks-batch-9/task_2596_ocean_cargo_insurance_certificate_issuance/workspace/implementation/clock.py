"""The logical clock (PRD section 2.6).

Before any request sets it the logical clock reads exactly 2026-08-01T00:00:00Z
and it never falls back to real wall-clock time.
"""
from datetime import datetime, timezone, timedelta

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(value):
    _state["now"] = value


def iso(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    v = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond // 1000,
    )


def midnight(value):
    """Normalise an instant to its whole calendar date at 00:00:00Z."""
    if value is None:
        return None
    v = value.astimezone(timezone.utc)
    return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)


def is_midnight(value):
    v = value.astimezone(timezone.utc)
    return (v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0)


def plus_days(value, days):
    return value + timedelta(days=int(days))


def plus_minutes(value, minutes):
    return value + timedelta(minutes=int(minutes))
