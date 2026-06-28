"""ISO 8601 datetime parsing for request inputs."""
from datetime import datetime, timezone

from errors import err


def parse_iso8601(value, field="datetime"):
    if not isinstance(value, str):
        raise err("ERR_VALIDATION", f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_VALIDATION", f"{field} must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
