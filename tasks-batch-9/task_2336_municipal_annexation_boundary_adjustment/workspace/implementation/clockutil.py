"""Logical-clock time helpers (PRD §2.4, §2.5).

Timestamps are ISO 8601 UTC with exactly three fractional digits and a trailing Z.
Nothing here consults wall-clock time except `wall_now`, which is used only for the
envelope's `api_request_timestamp` (request metadata, not a domain rule).
"""

import re
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc

_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?([Zz]|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MMDD_RE = re.compile(r"^\d{2}-\d{2}$")


def wall_now():
    return datetime.now(UTC)


def iso3(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _DT_RE.match(text):
        return None
    normalized = text.replace(" ", "T").replace("t", "T")
    if normalized.endswith("Z") or normalized.endswith("z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(value):
    """Parse a strict YYYY-MM-DD string into a date, or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def valid_month_day(value):
    if not isinstance(value, str) or not _MMDD_RE.match(value.strip()):
        return False
    month, day = int(value[0:2]), int(value[3:5])
    if month < 1 or month > 12:
        return False
    try:
        date(2004, month, day)  # leap year, so 02-29 is admissible
    except ValueError:
        return False
    return True


def month_day_in_year(year, month_day):
    month, day = int(month_day[0:2]), int(month_day[3:5])
    while day > 1:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, 1)


def fiscal_year_end(reference_date, month_day):
    """The fiscal year end at or after `reference_date` (PRD §3.8, §3.9)."""
    candidate = month_day_in_year(reference_date.year, month_day)
    if reference_date <= candidate:
        return candidate
    return month_day_in_year(reference_date.year + 1, month_day)


def add_days(instant, days):
    return instant + timedelta(days=int(days))


def days_inclusive(start_date, end_date):
    return (end_date - start_date).days + 1
