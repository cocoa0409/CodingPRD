"""Logical server clock, driven by /_clock/set_current_utc for temporal tests.

The clock governs every temporal check: window validity at application, lead
time at cancellation, completion/no-show eligibility, COI expiry, and lottery
close. It defaults to real UTC ("now") until a test sets it explicitly.
"""
from datetime import datetime, timezone

_current = None  # type: datetime | None


def reset():
    global _current
    _current = None


def set_current(dt):
    global _current
    _current = dt


def now():
    if _current is not None:
        return _current
    return datetime.now(timezone.utc)
