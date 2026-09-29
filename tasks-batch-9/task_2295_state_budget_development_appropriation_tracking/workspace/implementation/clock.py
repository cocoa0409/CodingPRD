"""The server-held logical clock (PRD section 2.6).

At startup the clock reads exactly 2026-08-01T00:00:00Z; the server never falls
back to the host's wall-clock time.
"""

from datetime import datetime, timezone

STARTUP_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = STARTUP_INSTANT


def get_now():
    return _now


def set_now(dt):
    global _now
    _now = dt.astimezone(timezone.utc)
    return _now


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt(_now)
