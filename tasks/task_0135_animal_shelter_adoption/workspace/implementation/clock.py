"""Server-controlled logical UTC clock.

Time-sensitive rules (stray-hold gate, foster cooldown, board day count) read from
this logical clock rather than wall-clock time. POST /_clock/set overrides it.
All system-assigned timestamps (intake_at, start_at, created_at, etc.) read `now()`.
"""
from datetime import datetime, timezone

_override = None  # datetime in UTC, or None to fall back to wall clock


def now():
    """Return the current logical UTC datetime (override if set, else wall clock)."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def set_clock(dt):
    """Pin the logical clock to a supplied aware UTC datetime."""
    global _override
    _override = dt


def reset():
    global _override
    _override = None


def to_iso(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits and Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # milliseconds, three fractional digits, trailing Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp into an aware UTC datetime. Raises ValueError on bad input."""
    if not isinstance(s, str) or not s:
        raise ValueError("invalid datetime string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
