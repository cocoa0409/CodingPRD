"""Logical clock with manual advance for tests."""
import datetime as _dt
from threading import Lock


_offset_seconds = 0
_lock = Lock()


def now():
    """Return logical UTC datetime (real now + accumulated offset)."""
    with _lock:
        return _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=_offset_seconds)


def advance(seconds):
    global _offset_seconds
    with _lock:
        _offset_seconds += int(seconds)


def iso_now():
    return format_dt(now())


def format_dt(dt):
    """ISO 8601 UTC with three fractional digits, suffixed Z."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    dt = dt.astimezone(_dt.timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = dt.microsecond // 1000
    return f"{s}.{millis:03d}Z"


def parse_dt(s):
    """Parse ISO 8601 UTC datetime string. Returns timezone-aware datetime."""
    if s is None:
        return None
    if isinstance(s, _dt.datetime):
        if s.tzinfo is None:
            return s.replace(tzinfo=_dt.timezone.utc)
        return s.astimezone(_dt.timezone.utc)
    # Normalize Z suffix
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(s)
    except ValueError:
        raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


def parse_date(s):
    """Parse ISO date YYYY-MM-DD into date."""
    if s is None:
        return None
    return _dt.date.fromisoformat(s)
