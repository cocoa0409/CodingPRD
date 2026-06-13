"""Logical UTC clock for deterministic time-dependent behaviour.

The clock can be overridden via POST /_clock/set. When never set, it falls back
to the real wall clock. The store starts empty on every boot (per-test isolation),
so the override is reset to None on each fresh process automatically.
"""
from datetime import datetime, timezone

# When None, use real wall clock. Otherwise a fixed datetime (aware, UTC).
_now_override = None


def set_now(dt):
    global _now_override
    _now_override = dt


def now():
    if _now_override is not None:
        return _now_override
    return datetime.now(timezone.utc)


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, 'Z' suffix."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    # milliseconds = first three digits of microseconds
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % millis


def parse_ts(s):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
