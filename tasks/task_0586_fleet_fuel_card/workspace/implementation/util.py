"""Rounding, datetime, and numeric helpers.

PRD §2.6: all money in integer cents; non-integer intermediates are rounded
HALF UP.  Fuel economy -> 1 decimal, taxable gallons -> 3 decimals.  Totals are
formed by rounding each part first and summing the rounded parts.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def dec(value):
    """Exact Decimal from an int/float/str/Decimal (via str to dodge binary float noise)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    return Decimal(str(value))


def round_half_up(value, places=0):
    """Round HALF UP to `places` decimals.  Returns Decimal."""
    q = Decimal(1).scaleb(-places)  # 1, 0.1, 0.001, ...
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round HALF UP to a whole number of cents -> int."""
    return int(round_half_up(value, 0))


def num(value):
    """Render a Decimal as a JSON-friendly number."""
    d = dec(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# --------------------------------------------------------------------------
# Datetimes
# --------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 datetime.  Returns a tz-aware UTC datetime or raises ValueError."""
    if not isinstance(value, str) or not value:
        raise ValueError("not a datetime string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_dt(value):
    """Canonical ISO 8601 UTC with exactly three fractional digits (PRD §2.5)."""
    if value is None:
        return None
    d = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond // 1000,
    )
