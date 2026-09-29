"""Server-held logical clock (PRD 2.4).

Startup value is exactly 2026-08-01T00:00:00Z; nothing in the system ever reads
wall-clock time.
"""
from datetime import datetime, timezone

STARTUP_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = STARTUP_UTC


def now():
    return _current


def set_now(dt):
    global _current
    _current = dt.astimezone(timezone.utc)
    return _current


def reset():
    global _current
    _current = STARTUP_UTC


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse(value):
    """Parse an ISO-8601 instant. Returns None when the value is unparsable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
