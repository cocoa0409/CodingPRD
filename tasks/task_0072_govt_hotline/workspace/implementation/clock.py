"""Logical clock. Wraps wall-clock time + a test-only offset advanced by /_clock/advance.

All timestamps in the system go through this module so that the sweep, deadline checks,
warning_state computation, and survey-expiry arithmetic operate against a single
deterministic clock that tests can manipulate."""

from datetime import datetime, timezone, timedelta
import threading

_lock = threading.Lock()
_offset_seconds = 0  # added to wall-clock UTC


def now() -> datetime:
    """Return the current logical UTC datetime (wall-clock + offset)."""
    with _lock:
        return datetime.now(timezone.utc) + timedelta(seconds=_offset_seconds)


def now_iso() -> str:
    """ISO 8601 UTC string with three fractional digits, suffixed Z."""
    return format_dt(now())


def advance_seconds(seconds: int) -> None:
    """Advance the logical clock by `seconds`."""
    global _offset_seconds
    with _lock:
        _offset_seconds += int(seconds)


def get_offset_seconds() -> int:
    with _lock:
        return _offset_seconds


def format_dt(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 UTC string with a trailing Z (or +00:00)."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)
