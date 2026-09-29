"""The logical clock (PRD 2.4).

The server never reads wall-clock time for a business decision.  A single
logical clock reads exactly 2026-08-01T00:00:00Z until a platform administrator
moves it through POST /_clock/set_current_utc.  Every deadline, cure-window,
promotion-window, bond-expiry and sweep-eligibility comparison, and every
timestamp the server stamps onto a record, reads this clock.
"""
from dates import UTC, fmt, midnight

DEFAULT_INSTANT = midnight(2026, 8, 1)

_current = DEFAULT_INSTANT


def now():
    """The logical clock's current value as an aware UTC datetime."""
    return _current


def now_iso():
    """The logical clock's current value in the canonical wire format."""
    return fmt(_current)


def set_now(instant):
    global _current
    _current = instant.astimezone(UTC)
    return _current


def reset():
    global _current
    _current = DEFAULT_INSTANT
