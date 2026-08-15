"""Logical clock per PRD §2.5.

Startup default: exactly 2026-08-01T00:00:00Z. Never falls back to wall-clock
time. Advanced only via POST /_clock/set_current_utc.
"""

from datetime import datetime, timezone

_DEFAULT = "2026-08-01T00:00:00Z"

_current: datetime = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_iso(s: str) -> datetime:
    """Parse an ISO8601 string into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt: datetime) -> str:
    """Serialize an aware datetime to ISO8601 UTC with three fractional digits and Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now() -> datetime:
    return _current


def now_iso() -> str:
    return to_iso(_current)


def set_current(to: datetime):
    global _current
    _current = to


def reset():
    """Reset to the startup default (used on fresh boot)."""
    global _current
    _current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
