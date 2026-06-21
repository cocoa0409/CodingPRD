"""The test-driving clock (PRD §2.9).

The service maintains a single logical UTC clock that governs every time
comparison: offer expiry, on-time determination, and the day count for daily
interest accrual. Unless the clock has been set, the system uses real UTC time.
"""
from datetime import datetime, timezone

# When None, real UTC time is used.
_override = None


def reset():
    global _override
    _override = None


def set_now(dt):
    """dt is a timezone-aware datetime (UTC)."""
    global _override
    _override = dt


def now():
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)
