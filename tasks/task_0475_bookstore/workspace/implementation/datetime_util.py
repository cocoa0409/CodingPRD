"""ISO 8601 datetime parsing and formatting helpers."""
from datetime import datetime, timezone

from errors import err, ERR_INVALID_REQUEST


def parse_iso8601(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        raise err(ERR_INVALID_REQUEST, "Timestamp must be an ISO 8601 string")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Malformed ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
