"""Server-held logical clock.

PRD 2.6: the server holds a logical clock whose value at process start is exactly
2026-08-01T00:00:00Z.  Every timestamp the server stamps and every temporal
comparison it makes reads this clock; real wall-clock time is never used for a
business decision.
"""

import calendar
import re
from datetime import datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT_NOW


def now() -> datetime:
    return _now


def set_now(value: datetime) -> None:
    global _now
    _now = value


_DT_PATTERNS = (
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def parse_datetime(raw):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    parsed = None
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        # Trim over-long fractional parts (Python < 3.11 rejects them).
        trimmed = re.sub(r"(\.\d{1,6})\d+", r"\1", candidate)
        try:
            parsed = datetime.fromisoformat(trimmed)
        except ValueError:
            parsed = None
    if parsed is None:
        for pattern in _DT_PATTERNS:
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(value):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if value is None:
        return None
    moment = value.astimezone(timezone.utc)
    millis = moment.microsecond // 1000
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % millis


def add_days(value: datetime, days: int) -> datetime:
    return value + timedelta(days=days)


def add_months(value: datetime, months: int) -> datetime:
    total = value.month - 1 + months
    year = value.year + total // 12
    month = total % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def whole_months_between(start: datetime, end: datetime) -> int:
    """Whole calendar months elapsed from start to end, truncated, never negative."""
    if start is None or end is None:
        return 0
    if end <= start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if months < 0:
        return 0
    while months > 0 and add_months(start, months) > end:
        months -= 1
    while add_months(start, months + 1) <= end:
        months += 1
    return max(0, months)
