"""Time utilities with a logical-clock offset driven by /_clock/advance."""

from datetime import datetime, timedelta, timezone
from threading import RLock


_CLOCK_OFFSET = timedelta(0)
_CLOCK_LOCK = RLock()


def _real_now():
    return datetime.now(timezone.utc)


def now_utc() -> datetime:
    with _CLOCK_LOCK:
        return _real_now() + _CLOCK_OFFSET


def advance(minutes: int) -> datetime:
    global _CLOCK_OFFSET
    with _CLOCK_LOCK:
        _CLOCK_OFFSET = _CLOCK_OFFSET + timedelta(minutes=minutes)
        return _real_now() + _CLOCK_OFFSET


def reset_clock():
    global _CLOCK_OFFSET
    with _CLOCK_LOCK:
        _CLOCK_OFFSET = timedelta(0)


def _format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc_now_iso() -> str:
    return _format_iso(now_utc())


def to_iso(dt) -> str:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return _format_iso(dt)


def parse_iso(value):
    """Parse an ISO 8601 UTC timestamp. Returns datetime in UTC, or None if value is None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def start_of_today_utc(reference=None) -> datetime:
    ref = reference if reference is not None else now_utc()
    return ref.replace(hour=0, minute=0, second=0, microsecond=0)
