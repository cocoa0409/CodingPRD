"""Server-controlled logical clock.

At startup the clock reads exactly 2026-01-01T00:00:00Z and stays there until
moved; it never falls back to real wall-clock time (PRD §3.10).
"""
from datetime import datetime, timezone

# Logical-clock current instant. Default per PRD §3.10 / scaffold endpoint note.
_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _DEFAULT


def now():
    """Return the current logical-clock instant as an aware UTC datetime."""
    return _current


def set_current(dt):
    """Set the logical clock to the supplied aware UTC datetime."""
    global _current
    _current = dt
