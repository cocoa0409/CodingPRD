"""Logical UTC clock. Defaults to 2026-05-01T00:00:00Z at startup and never
falls back to the wall clock. Driven by POST /nabs/_clock/set_current_utc."""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_now = _DEFAULT


def now():
    return _now


def today():
    return _now.date()


def set_now(dt):
    global _now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _now = dt


def reset():
    global _now
    _now = _DEFAULT
