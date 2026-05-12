"""Logical clock used for deterministic test-driving.

The clock can be advanced via POST /_clock/advance. When the clock has not been
advanced, the wall clock is used.
"""

from datetime import datetime, timezone

_simulated_now = None


def now():
    if _simulated_now is not None:
        return _simulated_now
    return datetime.now(timezone.utc)


def advance_to(dt):
    global _simulated_now
    _simulated_now = dt


def reset():
    global _simulated_now
    _simulated_now = None


def iso_format(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 string into a UTC-aware datetime."""
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError(f"Expected ISO 8601 string, got {type(s).__name__}")
    txt = s
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
