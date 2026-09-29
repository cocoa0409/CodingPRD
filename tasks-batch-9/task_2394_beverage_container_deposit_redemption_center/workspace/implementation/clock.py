"""Logical clock. Never falls back to wall-clock time."""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = DEFAULT_NOW


def reset():
    global _current
    _current = DEFAULT_NOW


def now():
    return _current


def set_now(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt(_current)


def today():
    d = _current.astimezone(timezone.utc)
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def date_of(dt):
    d = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_iso(text):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_stamp(text):
    """Parse a stored timestamp string produced by fmt()."""
    return parse_iso(text)
