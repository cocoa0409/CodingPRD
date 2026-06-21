"""Datetime helpers and ISO 8601 UTC formatting with three fractional digits."""
from datetime import datetime, timezone


def now_iso():
    """Server wall-clock timestamp (used for created_at/updated_at and meta)."""
    return format_iso(datetime.now(timezone.utc))


def format_iso(dt):
    """ISO 8601 UTC string with exactly three fractional digits and a Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts trailing 'Z' or an explicit offset. Raises ValueError on bad input.
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
