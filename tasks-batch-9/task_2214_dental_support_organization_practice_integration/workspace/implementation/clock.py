"""The logical clock.

All time in this system comes from a logical clock, never from wall-clock time.
It starts at exactly 2026-08-01T00:00:00Z on a fresh process and only ever moves
forward through POST /dso/_clock/set_current_utc.
"""

import calendar
from datetime import datetime, timedelta, timezone

from errors import invalid

EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = EPOCH


def now():
    return _now


def set_now(value):
    global _now
    _now = value


def reset():
    global _now
    _now = EPOCH


def parse_iso(raw, field="timestamp"):
    """Parse an ISO 8601 UTC date-time. Raises ERR_INVALID_REQUEST when malformed."""
    if not isinstance(raw, str):
        raise invalid("'%s' must be an ISO 8601 UTC date-time string." % field)
    text = raw.strip()
    if not text:
        raise invalid("'%s' must be an ISO 8601 UTC date-time string." % field)
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise invalid("'%s' must be an ISO 8601 UTC date-time string." % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_iso(value):
    """Render as ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def to_iso_instant(value):
    """Render a business instant as ISO 8601 UTC.

    Business date-time fields (§2.4's list of clock-stamped instants plus the
    client-supplied windows and participation dates) are echoed in the same
    whole-second form the logical clock and the request bodies use — the PRD
    writes those instants as `2026-08-01T00:00:00Z`. Only `created_at` and the
    envelope's `api_request_timestamp` are mandated to carry three fractional
    digits, so a sub-second instant still renders with them.
    """
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    value = value.astimezone(timezone.utc)
    if value.microsecond:
        return to_iso(value)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
    )


def whole_days_between(start, end):
    """floor((end - start) / 86400 seconds); exact for negative spans too."""
    delta = end - start
    return delta.days


def add_days(value, days):
    return value + timedelta(days=days)


def add_months(value, months):
    """Calendar-month addition with end-of-month clamping."""
    total = value.month - 1 + int(months)
    year = value.year + total // 12
    month = total % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


OPEN_ENDED = datetime(9999, 12, 31, 0, 0, 0, tzinfo=timezone.utc)
