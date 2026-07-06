"""Logical clock. Default at startup is 2026-03-01T00:00:00Z."""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = _DEFAULT


def get_now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def now_iso():
    return iso(_now)


def iso(dt):
    # ISO 8601 UTC with three fractional digits, Z suffix.
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(s, str) or not s:
        raise ValueError("not a datetime string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
