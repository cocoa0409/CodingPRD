"""Logical clock that can be advanced by the test harness.

All server-side timestamps come through `now()` / `now_iso()` so the harness
can fast-forward simulation time deterministically via POST /_clock/advance.
"""
import threading
from datetime import datetime, timedelta, timezone


_LOCK = threading.Lock()
# Offset applied to wall-clock time. The "logical now" is wall_clock + _offset.
# We anchor to wall-clock so timestamps still look real, but each /_clock/advance
# call shifts the reference forward.
_offset = timedelta(0)


def now() -> datetime:
    with _LOCK:
        return datetime.now(timezone.utc) + _offset


def now_iso() -> str:
    """ISO 8601 UTC timestamp with millisecond (3 fractional digit) precision."""
    d = now()
    # Format with milliseconds, trailing 'Z'.
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def advance_seconds(seconds: int) -> dict:
    global _offset
    before = now()
    with _LOCK:
        _offset = _offset + timedelta(seconds=int(seconds))
    after = now()
    crossed_midnight = before.date() != after.date()
    return {
        "seconds_advanced": int(seconds),
        "previous_time": before.strftime("%Y-%m-%dT%H:%M:%S.") + f"{before.microsecond // 1000:03d}Z",
        "current_time": after.strftime("%Y-%m-%dT%H:%M:%S.") + f"{after.microsecond // 1000:03d}Z",
        "crossed_midnight": crossed_midnight,
    }


def start_of_utc_day(d: datetime | None = None) -> datetime:
    if d is None:
        d = now()
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
