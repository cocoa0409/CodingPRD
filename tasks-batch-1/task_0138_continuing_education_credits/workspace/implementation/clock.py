"""Logical server clock (PRD §2.11).

Time-dependent logic — deadline reminders, audit cooldowns, temporal window
checks — reads this single server-side current-UTC clock, NOT wall-clock time.
The test-driving endpoint POST /_clock/set_current_utc advances it.

The clock starts uninitialized and falls back to real UTC until a test sets it.
"""

from datetime import datetime, timezone

# Module-global so it survives across requests within a single server process.
_current_utc = None


def now():
    """Return the current logical UTC clock as a tz-aware datetime."""
    if _current_utc is not None:
        return _current_utc
    return datetime.now(timezone.utc)


def set_now(dt):
    global _current_utc
    _current_utc = dt
