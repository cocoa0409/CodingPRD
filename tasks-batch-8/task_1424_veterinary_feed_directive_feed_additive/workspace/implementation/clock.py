"""Logical clock per PRD section 2.5. Starts at 2026-08-01T00:00:00Z."""

from datetime import datetime, timezone


DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT_NOW


def now():
    return _now


def set_now(dt):
    global _now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _now = dt.astimezone(timezone.utc)
    return _now
