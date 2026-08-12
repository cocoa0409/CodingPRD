"""Logical clock module. Startup default is exactly 2026-05-01T00:00:00Z.
The logical clock never falls back to wall-clock time."""
from datetime import datetime, timezone

DEFAULT_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT_START


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def iso(dt):
    """Format datetime as ISO8601 UTC with exactly 3 fractional digits, Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def datetime_max():
    return datetime.max.replace(tzinfo=timezone.utc)


def parse_iso(s):
    """Parse an ISO8601 timestamp (with Z or offset) into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
