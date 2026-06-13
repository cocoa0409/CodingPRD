"""Server clock. Can be pinned to a fixed UTC instant for deterministic time math."""
from datetime import datetime, timezone

_pinned = None  # type: ignore


def set_pinned(dt):
    global _pinned
    _pinned = dt


def now():
    """Return current server-clock instant as a timezone-aware UTC datetime."""
    if _pinned is not None:
        return _pinned
    return datetime.now(timezone.utc)


def now_iso():
    return format_iso(now())


def format_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # milliseconds precision
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime."""
    if s is None:
        return None
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
