"""Logical clock + ISO-8601 helpers. All time-dependent behavior reads from
this clock, never from wall-clock time. Startup default is exactly
2026-08-01T00:00:00Z."""
import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    with _lock:
        return _now


def set_now(dt):
    global _now
    with _lock:
        _now = dt


def parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_fmt(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
