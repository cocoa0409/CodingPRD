"""Monetary precision helpers (PRD §2.7). All money is whole cents. Non-integer
cent results use half-up rounding — a value exactly halfway between two whole
cents rounds up to the larger cent. Never use float for money."""
from decimal import Decimal, ROUND_HALF_UP


def D(x):
    return Decimal(str(x))


def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, half up."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
