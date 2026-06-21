"""Logical UTC clock. Drives every 'current clock' comparison.

The clock defaults to real wall-clock UTC until a test sets it explicitly via
POST /_clock/set_current_utc. Because the test harness restarts the server before
every test, the clock resets to real time on each boot (no carry-over state).
"""
from datetime import datetime, timezone

_override = None  # datetime (aware UTC) or None


def set_now(dt):
    global _override
    _override = dt


def now():
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def reset():
    global _override
    _override = None
