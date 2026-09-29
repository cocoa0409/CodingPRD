"""Rounding discipline (PRD 2.7): liters 3dp half-up, money whole cents half-up."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

CENT = Decimal("1")
LITER_Q = Decimal("0.001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu_liters(value):
    """round_half_up to 3 decimal places."""
    return dec(value).quantize(LITER_Q, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """round_half_up to whole cents; returns int."""
    return int(dec(value).quantize(CENT, rounding=ROUND_HALF_UP))


def floor_cents(value):
    """truncate downward to a whole cent; returns int."""
    return int(dec(value).quantize(CENT, rounding=ROUND_FLOOR))


def liters_out(value):
    """JSON representation of a liter quantity (3dp)."""
    if value is None:
        return None
    return float(rhu_liters(value))
