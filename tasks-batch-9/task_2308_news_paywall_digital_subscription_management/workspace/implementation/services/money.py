"""Rounding discipline (PRD 2.6): round half up, applied in pinned orders."""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("1")
TWO_PLACES = Decimal("0.01")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value):
    """Round a fractional-cent amount to a whole number of cents, half up."""
    return int(dec(value).quantize(CENT, rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round to two decimal places, half up (engagement scores)."""
    return dec(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def as_number(value):
    """Render a two-decimal Decimal as a JSON number."""
    return float(value)
