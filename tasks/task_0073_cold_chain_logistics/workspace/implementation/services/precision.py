"""Precision and rounding helpers."""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up_2(value) -> Decimal:
    """Round a numeric value to 2 decimals, half up. Returns a Decimal."""
    d = Decimal(str(value))
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_half_up_4(value) -> Decimal:
    d = Decimal(str(value))
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round_half_up_int(value) -> int:
    """Round any numeric to the nearest integer, half up."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_float_2(value) -> float:
    return float(round_half_up_2(value))


def to_float_4(value) -> float:
    return float(round_half_up_4(value))
