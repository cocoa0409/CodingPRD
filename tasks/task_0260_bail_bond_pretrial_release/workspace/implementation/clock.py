"""Test-driving logical clock.

PRD §3.9: SystemAdmin pins the logical clock to a fixed instant via
POST /_clock/set_current_utc {to_iso8601}. Until then, reads return real UTC.
All temporal rules read now_utc() / now_iso().
"""
from datetime import datetime, timezone

# When None, the clock falls back to real wall-clock UTC. Otherwise pinned.
_pinned = None  # datetime (tz-aware UTC)


def set_clock(dt):
    global _pinned
    _pinned = dt


def reset_clock():
    global _pinned
    _pinned = None


def now_utc():
    if _pinned is not None:
        return _pinned
    return datetime.now(timezone.utc)


def now_iso():
    return iso(now_utc())


def iso(dt):
    """Render a tz-aware UTC datetime as ISO 8601 with exactly 3 fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, trailing Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 string into a tz-aware UTC datetime, or None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Accept trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Date-only form YYYY-MM-DD
        try:
            dt = datetime.strptime(value.strip(), "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
