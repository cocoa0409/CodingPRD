"""The logical clock (PRD §2.12) and ISO 8601 datetime helpers.

The server's notion of "now" can be pinned via POST /_clock/set_current_utc.
All week-boundary and period computations read from this logical clock.
"""
from datetime import datetime, timezone

# When set, this overrides the real wall clock for the server's notion of "now".
_pinned_now = None


def set_current_utc(dt):
    global _pinned_now
    _pinned_now = dt


def current_utc():
    if _pinned_now is not None:
        return _pinned_now
    return datetime.now(timezone.utc)


def now_iso8601():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return _format_iso(dt)


def _format_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso8601(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or None on failure."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
