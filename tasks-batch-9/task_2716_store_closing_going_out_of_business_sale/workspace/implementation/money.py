"""Monetary and ratio arithmetic (PRD 2.5). Never floats for money."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

ZERO = Decimal("0")
ONE = Decimal("1")
Q4 = Decimal("0.0001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_money(value):
    """Half-up to a whole cent, returned as int."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(value):
    """Half-up to four decimal places, returned as Decimal."""
    return dec(value).quantize(Q4, rounding=ROUND_HALF_UP)


def ratio4(numerator, denominator):
    """Four-decimal ratio; 0.0000 when the denominator is zero."""
    d = dec(denominator)
    if d == 0:
        return Decimal("0.0000")
    return round4(dec(numerator) / d)


def floor_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def num(value):
    """Render a Decimal ratio for JSON."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
