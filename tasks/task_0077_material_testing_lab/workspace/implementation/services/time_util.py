"""Logical clock + timestamp formatting helpers."""

from datetime import datetime, timezone, timedelta


# The system carries a logical clock that may be advanced via /_clock/advance.
# We track an offset (a timedelta) added to wall-clock UTC.
_clock_offset = timedelta(0)


def reset_clock():
    global _clock_offset
    _clock_offset = timedelta(0)


def now_dt():
    """Return current logical datetime (timezone-aware, UTC)."""
    return datetime.now(timezone.utc) + _clock_offset


def now_iso():
    """ISO 8601 UTC with three fractional digits, ending in 'Z'."""
    now = now_dt()
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def format_iso(dt):
    if dt is None:
        return None
    # Accept either ISO string or datetime.
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse ISO 8601 datetime string into timezone-aware UTC datetime.

    Accepts 'Z' suffix or +00:00 offsets.
    Returns datetime or raises ValueError.
    """
    if s is None:
        return None
    if isinstance(s, datetime):
        if s.tzinfo is None:
            s = s.replace(tzinfo=timezone.utc)
        return s.astimezone(timezone.utc)
    if not isinstance(s, str) or not s:
        raise ValueError("Invalid datetime string")
    cleaned = s.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def advance_clock_to(target_dt):
    """Advance the logical clock so that now_dt() == target_dt.

    Returns the previous logical now and the new logical now.
    Only moves forward; if target_dt is before current logical now, no change.
    """
    global _clock_offset
    current_logical = now_dt()
    if target_dt <= current_logical:
        return current_logical, current_logical
    wall_now = datetime.now(timezone.utc)
    _clock_offset = target_dt - wall_now
    return current_logical, target_dt


def today_utc():
    """Return today's date in UTC (under the logical clock)."""
    return now_dt().date()
