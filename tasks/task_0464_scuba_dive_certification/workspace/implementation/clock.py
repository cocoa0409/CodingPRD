"""Logical clock. Sole source of 'now' for all deadline/expiry/window math.

On startup the clock reads exactly 2026-01-01T00:00:00Z, and until it is
explicitly set it remains at that value and never falls back to wall-clock time.
"""
from datetime import datetime, timezone

# PRD 2.4: startup default
_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = _DEFAULT


def get_now():
    return _now


def set_now(dt):
    global _now
    _now = dt
