"""Server clock with test-driving override.

The PRD (3.10) exposes an internal clock-control capability that fixes the
server's notion of "now" to a supplied ISO 8601 instant. All created_at,
completed_at, and current-time reads use this fixed instant once set.
"""
from datetime import datetime, timezone

# When None, the real wall clock is used. Otherwise this datetime (tz-aware UTC)
# is returned by now().
_fixed_now = None


def set_now(dt):
    """dt: a tz-aware datetime in UTC, or None to clear the override."""
    global _fixed_now
    _fixed_now = dt


def now():
    """Return the current UTC datetime (tz-aware)."""
    if _fixed_now is not None:
        return _fixed_now
    return datetime.now(timezone.utc)


def reset():
    global _fixed_now
    _fixed_now = None


def iso(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits.

    e.g. 2025-05-24T10:30:00.123Z
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # microseconds -> milliseconds (three fractional digits)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % millis


def now_iso():
    return iso(now())
