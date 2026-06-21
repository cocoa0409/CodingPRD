"""Server clock. Defaults to real UTC; pinnable via /_clock/set for deterministic tests."""
from datetime import datetime, timezone

_pinned = {"now": None}  # datetime (tz-aware UTC) or None


def now():
    if _pinned["now"] is not None:
        return _pinned["now"]
    return datetime.now(timezone.utc)


def set_now(dt):
    _pinned["now"] = dt


def now_iso():
    """ISO 8601 UTC with three fractional digits, trailing Z."""
    return iso(now())


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, trailing Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 string into a tz-aware UTC datetime. Returns None on failure."""
    if s is None or not isinstance(s, str):
        return None
    raw = s.strip()
    if not raw:
        return None
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
