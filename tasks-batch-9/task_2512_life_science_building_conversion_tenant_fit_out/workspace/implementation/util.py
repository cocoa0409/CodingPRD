"""Decimal and ISO-8601 helpers.

PRD 2.7: every monetary amount, gallon quantity, airflow/power figure and
utilisation percentage is carried to two decimal places, rounded half up; the
suitability score to one decimal place and the utility headroom ratio to four.
All rounding is half up -- never Python's banker's rounding.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

Q1 = Decimal("0.1")
Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")


def dec(value):
    """Coerce an int/float/Decimal/str into a Decimal without binary noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rh(value, places=2):
    """round_half_up to `places` decimal places."""
    exponent = Decimal(1).scaleb(-places)
    return dec(value).quantize(exponent, rounding=ROUND_HALF_UP)


def q2(value):
    return rh(value, 2)


def q1(value):
    return rh(value, 1)


def q4(value):
    return rh(value, 4)


def num(value):
    """Serialise a Decimal as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def parse_iso(text):
    """Parse an ISO 8601 instant into an aware UTC datetime, or raise ValueError."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("not an ISO 8601 instant")
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_iso(moment):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if moment is None:
        return None
    utc = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second,
        utc.microsecond // 1000,
    )


def wall_now():
    return datetime.now(timezone.utc)
