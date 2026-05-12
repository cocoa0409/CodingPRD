"""Logical clock used by the system, plus ISO timestamp helpers."""
from datetime import datetime, timezone, date, timedelta


# The logical clock tracks the latest "now" used by clock-driven side effects.
# Tests advance it via POST /_clock/advance.
_logical_now: datetime = datetime.now(tz=timezone.utc)


def now() -> datetime:
    return _logical_now


def now_iso() -> str:
    return iso(_logical_now)


def set_now(dt: datetime) -> None:
    global _logical_now
    _logical_now = dt


def iso(dt: datetime) -> str:
    """ISO 8601 UTC with milliseconds and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse ISO 8601 datetime, accept Z suffix or offset."""
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


def parse_date(s: str) -> date:
    """Parse ISO date YYYY-MM-DD."""
    if s is None:
        raise ValueError("date is None")
    if not isinstance(s, str):
        raise ValueError("date is not a string")
    # Accept "YYYY-MM-DD" only.
    try:
        return date.fromisoformat(s)
    except Exception as e:
        raise ValueError(f"invalid ISO date: {s}") from e


def date_to_iso(d: date) -> str:
    return d.isoformat()


def daterange(start: date, end_exclusive: date):
    """Yield each date in the half-open interval [start, end)."""
    cur = start
    while cur < end_exclusive:
        yield cur
        cur = cur + timedelta(days=1)


def today_utc() -> date:
    return now().date()
