"""Server logical clock (PRD 3.8).

The server's notion of "current UTC time" can be overridden by a ShopManager via
POST /_clock/set_current_utc {to_iso8601}; it then returns that value until set
again. Warranty-window (3.8) and clock-conflict (3.9) checks read this clock.

Timestamps are ISO 8601 UTC with three fractional digits (PRD 2.4).
"""
from datetime import datetime, timezone

# When set, overrides wall-clock "now". None => use real wall clock.
_override = None  # datetime (tz-aware UTC)


def _fmt(dt):
    # ISO 8601 UTC with exactly three fractional digits, trailing Z.
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime.

    Accepts trailing 'Z' or explicit offset. Raises ValueError on bad input.
    """
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    """Current server UTC time as a tz-aware datetime."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def now_iso():
    """Current server UTC time formatted per PRD 2.4."""
    return _fmt(now())


def to_iso(dt):
    return _fmt(dt)


def set_now(dt):
    global _override
    _override = dt.astimezone(timezone.utc)


def reset():
    """Wipe clock override (called on process start; in-memory only)."""
    global _override
    _override = None
