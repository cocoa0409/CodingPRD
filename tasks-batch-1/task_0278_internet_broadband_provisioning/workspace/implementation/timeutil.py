"""ISO 8601 UTC timestamp helpers (PRD §2.2, §2.4, §2.8).

Timestamps are ISO 8601 UTC with three fractional digits, e.g.
"2025-05-24T10:30:00.123Z".
"""
from datetime import datetime, timezone


def parse_iso(value):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime.

    Returns None if the value is not a parseable ISO 8601 string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Accept trailing 'Z' as UTC.
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
