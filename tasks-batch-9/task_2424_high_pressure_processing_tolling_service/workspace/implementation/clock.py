"""Logical clock.

PRD 2.4: all time-dependent behaviour reads a logical clock rather than
wall-clock time.  Before any client sets it, the clock reads exactly
2026-08-01T00:00:00Z and it never falls back to the host's real time.
"""
from datetime import datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)
    return _state["now"]


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_seconds(dt, seconds):
    return dt + timedelta(seconds=int(seconds))
