"""Server-held logical clock (PRD §2.5, §3.14).

Every relative-time rule reads this clock rather than wall time. A manager-only
test-driving endpoint sets it. State is process-local and reset on each boot.
"""
from datetime import datetime, timezone

# The logical "now" instant, as a timezone-aware UTC datetime. Defaults to the
# real wall clock at boot until the test harness sets it.
_current = None


def reset():
    global _current
    _current = None


def set_now(dt):
    """dt: timezone-aware UTC datetime."""
    global _current
    _current = dt


def now():
    """Return the current logical instant as an aware UTC datetime."""
    if _current is not None:
        return _current
    return datetime.now(timezone.utc)


def now_iso():
    """ISO 8601 UTC with three fractional digits, 'Z' suffix (for envelope meta)."""
    return to_iso_millis(datetime.now(timezone.utc))


def to_iso_millis(dt):
    """Format an aware UTC datetime as ISO 8601 with milliseconds and 'Z'."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
