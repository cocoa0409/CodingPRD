"""Logical clock — singleton; advanced only via POST /_clock/advance."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .errors import ApiError


_ISO_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
)


def parse_iso(value: Optional[str]) -> datetime:
    if value is None:
        raise ApiError("ERR_BAD_REQUEST", "Missing timestamp.")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise ApiError("ERR_BAD_REQUEST", f"Invalid timestamp type: {type(value).__name__}")
    v = value.strip()
    # Try the standard ISO formats. Treat trailing 'Z' as UTC.
    try:
        if v.endswith("Z"):
            # Python's fromisoformat doesn't accept 'Z' until 3.11; handle uniformly.
            v2 = v[:-1] + "+00:00"
            return datetime.fromisoformat(v2)
        return datetime.fromisoformat(v)
    except ValueError:
        pass
    for fmt in _ISO_FORMATS:
        try:
            dt = datetime.strptime(v, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ApiError("ERR_BAD_REQUEST", f"Unparseable timestamp: {value!r}")


def format_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class _Clock:
    def __init__(self) -> None:
        self._now: datetime = datetime.now(tz=timezone.utc)

    @property
    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt

    def reset(self) -> None:
        self._now = datetime.now(tz=timezone.utc)


CLOCK = _Clock()
