"""Virtual clock for test orchestration.

The clock is advanced through POST /_clock/advance. All time-sensitive
business logic reads through `now()` so tests can deterministically move
the clock forward without sleeping.
"""

from datetime import datetime, timezone


_clock_now: datetime = datetime.now(timezone.utc)


def now() -> datetime:
    return _clock_now


def now_iso() -> str:
    return format_iso(_clock_now)


def format_iso(dt: datetime) -> str:
    """ISO-8601 UTC with milliseconds and a trailing 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp accepting 'Z' or explicit offsets."""
    if not isinstance(value, str):
        raise ValueError("expected ISO 8601 string")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def advance_ms(ms: int) -> datetime:
    global _clock_now
    if ms < 0:
        raise ValueError("advance_ms must be non-negative")
    from datetime import timedelta

    _clock_now = _clock_now + timedelta(milliseconds=ms)
    return _clock_now


def set_to(dt: datetime) -> datetime:
    global _clock_now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _clock_now = dt.astimezone(timezone.utc)
    return _clock_now
