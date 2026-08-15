"""Server-side logical clock (PRD 2.4).

Default before any call: exactly 2026-08-01T00:00:00Z. The clock never falls
back to wall-clock time; only POST /v1/_clock/set_current_utc moves it.
"""

from datetime import datetime, timezone

_current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _current


def set_current(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp; accepts trailing Z and fractional seconds."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
