"""Logical clock used by the system, plus ISO timestamp helpers."""
from datetime import datetime, timezone, timedelta


# The logical clock tracks the latest "now" used by clock-driven side effects.
# Tests advance it via POST /_clock/advance.
_logical_now: datetime = datetime.now(tz=timezone.utc)


def now() -> datetime:
    return _logical_now


def now_iso() -> str:
    return iso(_logical_now)


def set_now(dt: datetime) -> None:
    global _logical_now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    _logical_now = dt


def iso(dt: datetime) -> str:
    """ISO 8601 UTC with milliseconds and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse ISO 8601, accept Z suffix or offset. Returns timezone-aware UTC datetime."""
    if s is None:
        raise ValueError("timestamp is None")
    if not isinstance(s, str):
        raise ValueError("timestamp not a string")
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception as e:
        raise ValueError(f"invalid ISO 8601 timestamp: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def to_utc_midnight(dt: datetime) -> datetime:
    """Anchor to UTC midnight on the calendar day."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def date_only(dt: datetime) -> datetime:
    """Return the date portion as UTC midnight (truncating time)."""
    return to_utc_midnight(dt)


def is_first_of_month(dt: datetime) -> bool:
    """True iff dt is exactly UTC midnight on the 1st of a month."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.day == 1 and dt.hour == 0 and dt.minute == 0 and dt.second == 0 and dt.microsecond == 0


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def diff_days(later: datetime, earlier: datetime) -> int:
    """(later - earlier) in days, floored."""
    later = to_utc_midnight(later) if later.tzinfo is None else later.astimezone(timezone.utc)
    earlier = to_utc_midnight(earlier) if earlier.tzinfo is None else earlier.astimezone(timezone.utc)
    return (later - earlier).days
