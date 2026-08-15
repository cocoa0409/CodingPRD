"""The server-side logical clock (PRD §2.4).

Startup default is exactly 2026-08-01T00:00:00Z; the clock never falls back to
wall-clock time. All clock-sensitive rules (registration window, offer expiry,
day scheduling, late pickup) read this clock.
"""

from datetime import datetime, timezone

_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _DEFAULT


def now():
    """Current logical instant (tz-aware UTC)."""
    return _current


def today():
    """Current logical calendar date."""
    return _current.date()


def set_current(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)
    return _current
