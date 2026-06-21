"""Server clock. Defaults to real UTC; can be overridden by the test-driving
endpoint POST /_clock/set_current_utc (PRD 3.12)."""
from datetime import datetime, timezone

# When None, the server reads real wall-clock UTC. When set (by the test clock),
# all temporal checks and system timestamps read from this fixed instant.
_override = None  # datetime (tz-aware UTC) or None


def set_current_utc(dt):
    global _override
    _override = dt


def now():
    """Return the current server UTC time as a tz-aware datetime."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def now_iso():
    """ISO 8601 UTC instant with exactly three fractional digits, 'Z' suffix."""
    return format_iso(now())


def format_iso(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, three fractional digits, Z suffix
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
