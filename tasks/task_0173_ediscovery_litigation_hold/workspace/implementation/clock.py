"""Server clock — pinnable for test determinism via /_clock/set_current_utc."""
from datetime import datetime, timezone

_pinned = None  # datetime (tz-aware) or None


def set_now(dt):
    global _pinned
    _pinned = dt


def now():
    if _pinned is not None:
        return _pinned
    return datetime.now(timezone.utc)


def iso_now():
    return to_iso(now())


def to_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, Z suffix
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.

    Returns None if the value cannot be parsed.
    """
    if not isinstance(s, str) or not s:
        return None
    raw = s.strip()
    txt = raw
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
