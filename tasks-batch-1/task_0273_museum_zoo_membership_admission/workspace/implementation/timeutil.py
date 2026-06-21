"""ISO 8601 UTC datetime parsing / formatting with 3 fractional digits."""
from datetime import datetime, timezone, timedelta

from errors import invalid_request


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Accepts trailing 'Z', explicit offsets, or naive (assumed UTC). Raises
    ERR_INVALID_REQUEST on a malformed string.
    """
    if not isinstance(value, str) or not value.strip():
        raise invalid_request("Invalid datetime string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise invalid_request("Invalid datetime string: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def add_days(dt, days):
    return dt + timedelta(days=days)
