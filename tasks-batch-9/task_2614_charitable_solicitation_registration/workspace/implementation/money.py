"""Monetary and ratio precision helpers.

Every monetary field is an integer count of cents (PRD 2.6).  Where a
calculation multiplies cents by a fraction the intermediate product is rounded
half up to a whole number of cents.  Ratios are rounded half up to four decimal
places.  ``float`` is never used for the arithmetic itself.
"""
from decimal import Decimal, ROUND_HALF_UP

_ONE = Decimal(1)
_FOUR_PLACES = Decimal("0.0001")


def dec(value):
    """Coerce an int / float / str / Decimal into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up_cents(value):
    """Round a Decimal (or number) half up to a whole number of cents."""
    return int(dec(value).quantize(_ONE, rounding=ROUND_HALF_UP))


def round_half_up_ratio(value):
    """Round half up to four decimal places and return a JSON-friendly number."""
    quantized = dec(value).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)
    return float(quantized)
