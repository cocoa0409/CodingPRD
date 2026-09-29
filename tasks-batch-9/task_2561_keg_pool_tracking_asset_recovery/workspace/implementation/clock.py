"""Settable logical clock.

Before any client repositions it the logical clock reads exactly
2026-08-01T00:00:00Z.  The server must never fall back to wall-clock time.
"""
from datetime import datetime, timezone

DEFAULT_UTC = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

_current = DEFAULT_UTC


def now():
    return _current


def set_now(dt):
    global _current
    previous = _current
    _current = dt
    return previous
