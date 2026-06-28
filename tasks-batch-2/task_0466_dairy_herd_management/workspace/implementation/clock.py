"""Server logical clock (PRD §2.4).

On server startup the clock reads exactly 2026-01-01T00:00:00Z and until it
is explicitly set it stays at that default — it never falls back to wall-clock
time. All withhold / pregnancy-check / projection windows evaluate against it.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = DEFAULT_CLOCK


def now():
    """Return the current logical clock instant (tz-aware UTC datetime)."""
    return _current


def set_clock(instant):
    global _current
    _current = instant
    return _current
