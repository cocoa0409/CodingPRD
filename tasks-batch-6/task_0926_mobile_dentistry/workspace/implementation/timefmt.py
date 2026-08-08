"""Instant / date parsing and canonical rendering.

PRD 2.4: every instant-valued field in every response body is rendered as an
ISO 8601 UTC timestamp with exactly three fractional-second digits and a
trailing `Z`.  Caller-supplied instants are re-rendered canonically rather than
echoed verbatim, and comparisons happen at millisecond resolution on the
underlying values.  Every instant in this system -- server-written or
caller-supplied -- passes through `parse_instant` on the way in and
`render_instant` on the way out, so no code path can emit a differently shaped
instant.

PRD 2.4: date-valued fields are rendered as a bare `YYYY-MM-DD`.
"""

import re
from datetime import datetime, date, timedelta, timezone

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TimeFormatError(ValueError):
    """Raised when a supplied instant or date is not well formed."""


def parse_instant(value):
    """Parse an ISO 8601 instant into a millisecond-truncated aware UTC datetime."""
    if not isinstance(value, str):
        raise TimeFormatError("not a string")
    text = value.strip()
    if not text:
        raise TimeFormatError("empty")
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise TimeFormatError("malformed instant: %s" % value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    # Millisecond resolution: truncate (never round) sub-millisecond precision.
    return parsed.replace(microsecond=(parsed.microsecond // 1000) * 1000)


def render_instant(value):
    """Render an aware datetime as `YYYY-MM-DDTHH:MM:SS.mmmZ`, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        value = parse_instant(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    millis = value.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        millis,
    )


def parse_date(value):
    """Parse a strict `YYYY-MM-DD` calendar date."""
    if not isinstance(value, str):
        raise TimeFormatError("not a string")
    text = value.strip()
    if not _DATE_RE.match(text):
        raise TimeFormatError("malformed date: %s" % value)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise TimeFormatError("malformed date: %s" % value)


def render_date(value):
    """Render a date object (or pass through a well-formed string) as YYYY-MM-DD."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        value = value.date()
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def add_days(value, days):
    """Exact, month-length-aware calendar-day addition preserving the time of day."""
    return value + timedelta(days=days)


def add_hours(value, hours):
    return value + timedelta(hours=hours)


def add_business_days(base, n):
    """Step forward one calendar day at a time counting only Mon..Fri.

    The time of day is preserved throughout and no holiday calendar is applied.
    """
    current = base
    counted = 0
    while counted < n:
        current = current + timedelta(days=1)
        if current.weekday() < 5:
            counted += 1
    return current


def whole_days_between(earlier, later):
    """Exact count of day boundaries between two calendar dates."""
    return (later - earlier).days


def end_of_day_instant(day):
    """The `YYYY-MM-DDT23:59:59Z` instant for a calendar date."""
    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)


def instant_date(value):
    """The UTC calendar date of an instant."""
    return value.astimezone(timezone.utc).date()


__all__ = [
    "TimeFormatError",
    "parse_instant",
    "render_instant",
    "parse_date",
    "render_date",
    "add_days",
    "add_hours",
    "add_business_days",
    "whole_days_between",
    "end_of_day_instant",
    "instant_date",
    "date",
    "timedelta",
]
