"""Logical clock for the captive-insurance service.

The server keeps a logical "current UTC" instant. At startup it defaults to
2026-05-01T00:00:00Z; tests can move it via POST /_clock/set_current_utc.
All transitions whose preconditions or side effects reference current_utc read
from this module.
"""
from __future__ import annotations

from datetime import datetime, timezone

_EPOCH = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

_current: datetime = _EPOCH


def parse_ts(value):
    """Parse an ISO 8601 timestamp (accepts trailing 'Z'). Returns aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now() -> datetime:
    return _current


def now_iso() -> str:
    return fmt_ts(_current)


def set_current(value) -> bool:
    """Set the logical clock. Accepts an ISO string or datetime. Returns success."""
    global _current
    dt = parse_ts(value)
    if dt is None:
        return False
    _current = dt
    return True
