"""Logical clock. Starts at exactly 2026-08-01T00:00:00Z; monotonic."""
from datetime import datetime, timezone

_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _START


def now() -> datetime:
    return _current


def set_now(value: datetime) -> None:
    global _current
    _current = value


def iso_now() -> str:
    return iso_format(_current)


def iso_format(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(s):
    """Parse ISO 8601 input. Accepts trailing Z and offset forms, with or
    without fractional seconds. Returns aware datetime in UTC, or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if not txt:
        return None
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
