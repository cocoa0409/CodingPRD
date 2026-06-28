"""Monetary precision helpers (PRD §2.6).

All monetary amounts are integer cents. Every fractional cent is rounded
half-up (away from zero at the .5 boundary). Never use float for money.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric/Decimal value to the nearest integer, half-up (away from
    zero at exactly .5). Returns an int."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
