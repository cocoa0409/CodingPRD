"""Virtual clock — advanced via POST /_clock/advance, defaults to real UTC time."""
from datetime import datetime, timezone

_now_override = None


def get_now() -> datetime:
    global _now_override
    if _now_override is not None:
        return _now_override
    return datetime.now(timezone.utc)


def set_now(dt: datetime):
    global _now_override
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _now_override = dt.astimezone(timezone.utc)


def iso_now() -> str:
    return format_iso(get_now())


def format_iso(dt: datetime):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
