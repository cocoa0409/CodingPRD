"""Time utilities and a test-overridable server clock."""

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional


_OVERRIDE: Optional[datetime] = None
_LOCK = threading.RLock()


def set_clock(iso_str: str) -> datetime:
    """Advance the server clock to the given ISO 8601 instant."""
    global _OVERRIDE
    dt = parse_iso(iso_str)
    if dt is None:
        raise ValueError("invalid ISO 8601 string")
    with _LOCK:
        _OVERRIDE = dt
    return dt


def server_now() -> datetime:
    with _LOCK:
        if _OVERRIDE is not None:
            return _OVERRIDE
    return datetime.now(timezone.utc)


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(value) -> Optional[datetime]:
    """Parse an ISO 8601 instant; tolerate a trailing 'Z'."""
    if not isinstance(value, str) or not value:
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


def add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)
