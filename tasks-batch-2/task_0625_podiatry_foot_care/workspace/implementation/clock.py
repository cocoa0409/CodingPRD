"""Logical clock (PRD §2.5).

The server never reads wall-clock time for business decisions. At startup the
logical clock reads exactly 2026-01-01T00:00:00Z and holds that value until
explicitly moved. It never falls back to real-world time.
"""

from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = _DEFAULT


def reset():
    global _current
    _current = _DEFAULT


def set_current(dt):
    """dt is a timezone-aware datetime."""
    global _current
    _current = dt


def now():
    """Return the current logical clock instant (timezone-aware datetime)."""
    return _current


def current_date():
    """Return the date component of the logical clock."""
    return _current.date()
