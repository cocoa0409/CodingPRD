"""ISO 8601 UTC timestamp parsing and formatting (PRD §2.2, §2.4).

Stored/emitted timestamps are ISO 8601 UTC with exactly three fractional digits
and a trailing 'Z'.
"""
from datetime import datetime, timezone


def parse_iso8601(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ValueError on anything not parseable.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # milliseconds with three digits, then Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
