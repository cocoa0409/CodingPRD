"""Server clock + timestamp/duration helpers."""
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone


_CLOCK_LOCK = threading.RLock()
_CLOCK_OFFSET = timedelta(0)


def _real_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def now() -> datetime:
    """Return the (virtual) server clock instant in UTC."""
    with _CLOCK_LOCK:
        return _real_now() + _CLOCK_OFFSET


def advance(duration: timedelta) -> datetime:
    """Advance the virtual clock by the given duration. Returns the new instant."""
    global _CLOCK_OFFSET
    with _CLOCK_LOCK:
        _CLOCK_OFFSET = _CLOCK_OFFSET + duration
        return _real_now() + _CLOCK_OFFSET


def reset() -> None:  # pragma: no cover - utility
    global _CLOCK_OFFSET
    with _CLOCK_LOCK:
        _CLOCK_OFFSET = timedelta(0)


def iso(dt: datetime | None) -> str | None:
    """Format datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}T{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}.{ms:03d}Z"


_ISO_PARSE_PATTERNS = [
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d",
]


def parse_iso(s) -> datetime | None:
    """Parse an ISO8601 timestamp or date. Returns None when unparseable.

    Accepts trailing 'Z' (UTC), explicit offsets, or naive date strings.
    """
    if s is None:
        return None
    if isinstance(s, datetime):
        if s.tzinfo is None:
            return s.replace(tzinfo=timezone.utc)
        return s.astimezone(timezone.utc)
    if not isinstance(s, str):
        return None
    text = s.strip()
    if not text:
        return None
    # datetime.fromisoformat handles many shapes
    try:
        candidate = text
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    for pattern in _ISO_PARSE_PATTERNS:
        try:
            dt = datetime.strptime(text, pattern)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


_DURATION_RE = re.compile(
    r"^(?P<sign>[+-])?P"
    r"(?:(?P<years>\d+)Y)?"
    r"(?:(?P<months>\d+)M)?"
    r"(?:(?P<weeks>\d+)W)?"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?"
    r")?$"
)


def parse_duration(s) -> timedelta | None:
    """Parse a subset of ISO 8601 durations (no calendar arithmetic precision)."""
    if not isinstance(s, str):
        return None
    match = _DURATION_RE.match(s.strip())
    if not match:
        return None
    parts = match.groupdict()
    # We need at least one component besides the P
    if not any(parts[k] for k in ("years", "months", "weeks", "days", "hours", "minutes", "seconds")):
        return None
    sign = -1 if parts.get("sign") == "-" else 1
    days = 0.0
    days += int(parts["years"] or 0) * 365
    days += int(parts["months"] or 0) * 30
    days += int(parts["weeks"] or 0) * 7
    days += int(parts["days"] or 0)
    seconds = 0.0
    seconds += int(parts["hours"] or 0) * 3600
    seconds += int(parts["minutes"] or 0) * 60
    seconds += float(parts["seconds"] or 0)
    return sign * timedelta(days=days, seconds=seconds)


def anniversary_one_year_after(dt: datetime) -> datetime:
    """Return the same month/day exactly one year later (Feb 29 -> Feb 28)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    target_year = dt.year + 1
    month = dt.month
    day = dt.day
    # Handle Feb 29 → Feb 28
    try:
        return dt.replace(year=target_year, month=month, day=day)
    except ValueError:
        return dt.replace(year=target_year, month=month, day=28)


def march_first_of(year: int) -> datetime:
    return datetime(year=year, month=3, day=1, tzinfo=timezone.utc)


def is_at_least_years(birth: datetime, current: datetime, years: int) -> bool:
    """Return True iff (current - birth) >= the given years (date-only semantics)."""
    threshold_year = current.year - years
    threshold = current.replace(year=threshold_year)
    return birth <= threshold
