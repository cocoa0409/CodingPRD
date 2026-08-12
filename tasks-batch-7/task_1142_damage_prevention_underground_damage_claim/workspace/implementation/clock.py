"""Logical clock. Startup default is exactly 2026-05-01T00:00:00Z.
The server never reads wall-clock time for business logic."""

from datetime import datetime, timezone


_STARTUP_DEFAULT = "2026-05-01T00:00:00+00:00"

_current_utc = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_current_utc():
    return _current_utc


def set_current_utc(dt):
    global _current_utc
    _current_utc = dt
