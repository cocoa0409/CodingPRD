"""Decimal precision helpers (PRD 2.8): round half up, never float money."""

from decimal import Decimal, ROUND_HALF_UP


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to whole cents and return a Python int."""
    return int(round_half_up(value, 0))


def ceil_int(value):
    value = dec(value)
    truncated = int(value)
    if value > truncated:
        truncated += 1
    return truncated


def as_number(value, places):
    """Serialize a Decimal with the declared precision as a JSON number."""
    if value is None:
        return None
    return float(round_half_up(value, places))
