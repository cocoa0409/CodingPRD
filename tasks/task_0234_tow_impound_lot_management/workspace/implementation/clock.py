"""Single logical UTC clock. PRD §2.4: an admin capability sets 'now' to an
explicit instant; until then 'now' is the real wall clock."""
from datetime import datetime, timezone

_override = None  # datetime in UTC, or None to use the real clock


def now():
    """Current logical time as a naive-UTC datetime (all stored times are naive UTC)."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc).replace(tzinfo=None)


def set_clock(dt):
    global _override
    _override = dt


def reset_clock():
    global _override
    _override = None


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp into a naive-UTC datetime. Returns None on failure."""
    if not isinstance(s, str) or not s:
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
