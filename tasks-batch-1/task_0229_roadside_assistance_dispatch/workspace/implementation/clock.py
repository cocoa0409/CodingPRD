"""Server clock. Pinnable for deterministic tests (PRD §2.10)."""
from datetime import datetime, timezone

_pinned = None  # datetime (tz-aware UTC) or None


def set_now(dt):
    """Pin the server clock to a tz-aware UTC datetime."""
    global _pinned
    _pinned = dt


def now():
    """Return the current server UTC instant (pinned if set)."""
    if _pinned is not None:
        return _pinned
    return datetime.now(timezone.utc)


def reset():
    global _pinned
    _pinned = None


def iso(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with exactly 3 fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    # microseconds -> milliseconds (truncate to 3 digits)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def now_iso():
    return iso(now())
