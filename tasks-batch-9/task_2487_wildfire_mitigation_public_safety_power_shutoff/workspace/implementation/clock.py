"""Logical clock (PRD 2.5).

The clock is process-local and always starts at exactly 2026-08-01T00:00:00Z.
The server never falls back to the host wall clock.
"""

from datetime import datetime, timezone

INITIAL = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = INITIAL
_raw = None


def now():
    return _now


def raw():
    """The exact string the client last supplied, when there was one."""
    return _raw


def set_now(dt, raw_value=None):
    global _now, _raw
    _now = dt
    _raw = raw_value


def reset():
    global _now, _raw
    _now = INITIAL
    _raw = None
