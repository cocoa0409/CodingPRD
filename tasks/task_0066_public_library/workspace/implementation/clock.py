"""Logical clock used by all time-gated logic in the system."""
import math
import re
from datetime import datetime, timezone, timedelta


def _truncate_to_ms(dt: datetime) -> datetime:
    """Truncate datetime to millisecond precision (drop sub-ms microseconds)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    us = dt.microsecond - (dt.microsecond % 1000)
    return dt.replace(microsecond=us)


_logical_now: datetime = _truncate_to_ms(datetime.now(tz=timezone.utc))


def now() -> datetime:
    return _logical_now


def now_iso() -> str:
    return iso(_logical_now)


def set_now(dt: datetime) -> None:
    global _logical_now
    _logical_now = _truncate_to_ms(dt)


def advance(delta: timedelta) -> None:
    set_now(_logical_now + delta)


def iso(dt: datetime) -> str:
    """ISO 8601 UTC with milliseconds and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse ISO 8601, accept Z suffix or offset. Returns timezone-aware UTC datetime."""
    if s is None:
        raise ValueError("timestamp is None")
    if not isinstance(s, str):
        raise ValueError("timestamp not a string")
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception as e:
        raise ValueError(f"invalid ISO 8601 timestamp: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


_ISO_DURATION_RE = re.compile(
    r"^(?P<sign>-)?P"
    r"(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?"
    r")?$"
)


def parse_iso_duration(s: str) -> timedelta:
    """Parse a (subset of) ISO 8601 duration. Supports days/hours/minutes/seconds.
    Examples: 'P1D', 'PT1H', 'P3DT2H30M', '-P1D'."""
    if not isinstance(s, str):
        raise ValueError("iso_duration must be a string")
    m = _ISO_DURATION_RE.match(s.strip())
    if not m:
        raise ValueError(f"invalid ISO 8601 duration: {s}")
    parts = m.groupdict()
    days = float(parts.get("days") or 0)
    hours = float(parts.get("hours") or 0)
    minutes = float(parts.get("minutes") or 0)
    seconds = float(parts.get("seconds") or 0)
    if days == 0 and hours == 0 and minutes == 0 and seconds == 0:
        # Allow PT0S only via explicit zero; but also accept P0D
        pass
    total = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if parts.get("sign") == "-":
        total = -total
    return total


def days_between_ceil(later: datetime, earlier: datetime) -> int:
    """Compute (later - earlier) in days, ceil-rounded.
    Returns 0 if later <= earlier.
    """
    if later <= earlier:
        return 0
    delta = later - earlier
    secs = delta.total_seconds()
    return int(math.ceil(secs / 86400.0))
