"""The logical service clock (PRD §2.4).

Every date comparison, window boundary, expiry check, elapsed-week count and gap
calculation reads this clock.  Real wall-clock time is never consulted for a
business rule.  At process startup the clock reads exactly 2026-08-01T00:00:00Z
and keeps reading that value until POST /_clock/set_current_utc moves it.
"""

from datetime import datetime, timezone

STARTUP_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = STARTUP_DEFAULT


def get_instant():
    """The full logical clock timestamp as an aware UTC datetime."""
    return _current


def set_instant(dt):
    global _current
    _current = dt.astimezone(timezone.utc)


def get_date():
    """The UTC calendar date of the current logical clock instant."""
    return _current.date()


def instant_str():
    """The clock instant as an ISO 8601 UTC string with three fractional digits."""
    dt = _current
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
