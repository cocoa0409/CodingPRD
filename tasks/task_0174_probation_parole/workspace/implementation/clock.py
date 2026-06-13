"""Logical server clock.

PRD §3.10: the system exposes a test-driving capability that sets the server's
current UTC clock and uses it thereafter for missed-check-in window comparison,
recurring-fee accrual, and months-served calculations.

The clock starts as the real wall clock and can be overridden via
POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

_override = None  # datetime in UTC, or None to fall back to wall clock


def now():
    """Return the current server UTC time as a timezone-aware datetime."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def set_now(dt):
    """Override the server clock with a timezone-aware UTC datetime."""
    global _override
    _override = dt


def reset():
    global _override
    _override = None
