"""Decimal-precision math helpers. Never use float for money (PRD §2.6)."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


def D(value):
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal/number to the nearest whole unit, half rounds up."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_to_int(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def clamp(lo, hi, value):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
