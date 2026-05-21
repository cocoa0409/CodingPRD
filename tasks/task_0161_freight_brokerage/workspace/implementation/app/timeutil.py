"""Time utilities — ISO 8601 UTC formatting with 3 fractional digits."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union


def iso_now(dt: Optional[datetime] = None) -> str:
    """Render *dt* (default: now) as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        dt = datetime.now(tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(value: Union[str, datetime]) -> datetime:
    """Parse an ISO 8601 timestamp string into a UTC-aware datetime.

    Raises ValueError on invalid input.  Accepts trailing 'Z' or explicit offset.
    """
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str):
            raise ValueError("not a string")
        s = value.strip()
        if not s:
            raise ValueError("empty timestamp")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
