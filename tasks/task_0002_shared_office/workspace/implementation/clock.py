"""Logical (virtual) clock for test-driving."""
from datetime import datetime, timezone

_now_override = None


def get_now() -> datetime:
    """Return the current virtual clock time as aware UTC datetime."""
    global _now_override
    if _now_override is not None:
        return _now_override
    return datetime.now(timezone.utc)


def set_now(dt: datetime):
    global _now_override
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _now_override = dt.astimezone(timezone.utc)


def iso_now() -> str:
    return format_iso(get_now())


def format_iso(dt: datetime) -> str:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{dt.microsecond // 1000:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp returning an aware UTC datetime."""
    if value is None:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
