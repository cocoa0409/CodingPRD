"""Server-side logical clock and ISO 8601 helpers per PRD §2.12."""
from datetime import datetime, timezone


# Server logical clock. Tests advance via POST /shuttle/_clock/advance.
# Default to current wall time at process start.
_logical_now: datetime = datetime.now(tz=timezone.utc)


def now() -> datetime:
    """Return the current server logical-clock instant as an aware UTC datetime."""
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


def reset_now() -> None:
    global _logical_now
    _logical_now = datetime.now(tz=timezone.utc)


def iso(dt: datetime) -> str:
    """ISO 8601 UTC with 3 fractional-digit milliseconds, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime. Accepts trailing 'Z'."""
    if not isinstance(s, str):
        raise ValueError("expected ISO 8601 string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
