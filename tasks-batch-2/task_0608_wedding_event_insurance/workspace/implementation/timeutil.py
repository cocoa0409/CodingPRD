"""ISO 8601 UTC helpers (PRD §2.4: three fractional digits)."""
from datetime import datetime, timezone

from errors import err


def fmt(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits (milliseconds)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ERR_INVALID_REQUEST when the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "datetime must be an ISO 8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "invalid ISO 8601 datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
