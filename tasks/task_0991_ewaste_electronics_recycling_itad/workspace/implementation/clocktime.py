"""Logical clock (PRD §2.9). Starts at exactly 2026-05-01T00:00:00Z and only
moves via POST /itad/_clock/set_current_utc. Never falls back to wall time."""

from datetime import datetime, timezone

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_now = _DEFAULT


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def parse_iso(value):
    """Parse an ISO 8601 datetime string. Accepts 'Z' or numeric offsets and
    optional fractional seconds. Naive values are read as UTC. Raises
    ValueError on anything unparseable."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _millis(dt):
    return dt.microsecond // 1000


def fmt_ts(dt):
    """Resource/request timestamp: always three fractional digits (PRD §2.2/§2.4)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{_millis(dt):03d}Z"


def fmt_dt(dt):
    """Echo-style datetime for client-supplied instants: seconds precision when
    no sub-second part was given, three fractional digits otherwise."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)
