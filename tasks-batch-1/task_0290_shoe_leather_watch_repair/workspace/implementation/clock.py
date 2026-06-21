"""Server-controlled logical clock (PRD §2.4).

The clock can be set by a ShopManager via POST /_clock/set. When unset it
falls back to wall-clock UTC. All server-stamped timestamps and every
eligibility comparison read 'now' from here.
"""
from datetime import datetime, timezone

_now_override = None  # datetime (tz-aware UTC) or None


def now():
    if _now_override is not None:
        return _now_override
    return datetime.now(timezone.utc)


def set_now(dt):
    global _now_override
    _now_override = dt


def reset():
    global _now_override
    _now_override = None


def to_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
