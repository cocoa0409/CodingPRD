"""Rounding, comparison and ISO-8601 helpers.

All percentage arithmetic goes through decimal.Decimal with ROUND_HALF_UP as
required by PRD 2.8: the value is rounded FIRST and only the rounded value is
ever compared against a threshold, and every threshold comparison is inclusive.
"""

import datetime as _dt
import re
from decimal import Decimal, ROUND_HALF_UP

ONE_DP = Decimal("0.1")
FOUR_DP = Decimal("0.0001")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def dec(value):
    """Coerce to Decimal without going through binary float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round1(value):
    """Round half up to one decimal place; returns a float for JSON output."""
    return float(dec(value).quantize(ONE_DP, rounding=ROUND_HALF_UP))


def round4(value):
    """Round half up to four decimal places; returns a float for JSON output."""
    return float(dec(value).quantize(FOUR_DP, rounding=ROUND_HALF_UP))


def pct1(numerator, denominator):
    """round_half_up(100 * numerator / denominator, 1); 0.0 when denominator is 0."""
    if denominator == 0:
        return 0.0
    return round1(dec(100) * dec(numerator) / dec(denominator))


def gte(a, b):
    """Inclusive >= comparison on already-rounded values."""
    return dec(a) >= dec(b)


def lte(a, b):
    return dec(a) <= dec(b)


def lt(a, b):
    return dec(a) < dec(b)


def add_pct(a, b):
    return round1(dec(a) + dec(b))


def min_pct(a, b):
    return round1(min(dec(a), dec(b)))


# --- time ---------------------------------------------------------------------

def iso(instant):
    """ISO-8601 UTC with exactly three fractional digits."""
    if instant is None:
        return None
    instant = instant.astimezone(_dt.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        instant.year, instant.month, instant.day,
        instant.hour, instant.minute, instant.second,
        instant.microsecond // 1000,
    )


def iso_date(value):
    if value is None:
        return None
    return value.isoformat()


def parse_instant(text):
    """Parse an ISO-8601 UTC instant. Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw or "T" not in raw:
        return None
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def parse_date(text):
    """Parse a strict YYYY-MM-DD calendar date. Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not _DATE_RE.match(raw):
        return None
    try:
        return _dt.date.fromisoformat(raw)
    except ValueError:
        return None


def date_part(instant):
    return instant.astimezone(_dt.timezone.utc).date()


def plus_days(instant, days):
    return instant + _dt.timedelta(days=days)


def plus_years(day, years):
    """Same month and day N calendar years later; 02-29 falls back to 02-28."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, month=2, day=28)


def day_span(opens_at, closes_at):
    """Whole-day span of a half-open datetime window."""
    return (closes_at - opens_at).total_seconds() / 86400.0


def inclusive_days(start_date, end_date):
    """Closed-inclusive day count: day difference plus one."""
    return (end_date - start_date).days + 1
