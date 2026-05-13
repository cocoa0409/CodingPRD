"""Simulated logical clock used by all temporal preconditions and calculations."""

from datetime import datetime, timezone
import threading


_lock = threading.RLock()
_now: datetime = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def now() -> datetime:
    with _lock:
        return _now


def advance_to(target: datetime) -> datetime:
    """Set the simulated clock to `target`.

    PRD §2.5 says the admin advances the clock 'to a supplied to instant'; it
    does not restrict the new value to be strictly later than the prior value.
    Treating this as an absolute set keeps the simulated clock a deterministic
    test driver across independent test cases.
    """
    global _now
    with _lock:
        _now = target
        return _now


def reset(target: datetime) -> None:
    """Reset the clock — for tests only."""
    global _now
    with _lock:
        _now = target


def format_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp; supports trailing Z and fractional seconds."""
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO 8601 timestamp: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
