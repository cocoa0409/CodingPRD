"""Timestamp, date and decimal helpers.

Every timestamp in this domain is rendered as an ISO 8601 UTC instant with
exactly three fractional digits (PRD §2.4), e.g. ``2026-08-01T00:00:00.000Z``.
"""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

UTC = timezone.utc

_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([Zz]|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _DT_RE.match(text):
        return None
    text = text.replace(" ", "T")
    if text[10] == "t":
        text = text[:10] + "T" + text[11:]
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _DATE_RE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def norm_dt(value):
    """Normalise an ISO instant string into the canonical stored rendering."""
    parsed = parse_dt(value)
    return iso(parsed) if parsed else None


def dt_of(stored):
    """Parse a stored canonical timestamp back into a datetime."""
    if stored is None:
        return None
    return parse_dt(stored)


def date_str(dt):
    return dt.astimezone(UTC).date().isoformat()


def D(value):
    """Build an exact Decimal from an int / float / str / Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value, places=2):
    """Round half up to ``places`` decimal places (PRD §2.7)."""
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def pct(value):
    """Render a percentage measure as a 2-decimal-place number."""
    return float(round_half_up(value, 2))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def add_days(dt, days):
    return dt + timedelta(days=days)


def minutes_to_hhmm(minutes):
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def hhmm_to_minutes(text):
    hours, mins = text.split(":")
    return int(hours) * 60 + int(mins)
