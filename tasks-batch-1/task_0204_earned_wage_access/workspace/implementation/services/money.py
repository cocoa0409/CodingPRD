"""Monetary precision helpers.

PRD §2.6: all monetary quantities are integer cents. Multiplications of
hours*rate or percentages are rounded HALF UP to the nearest whole cent. Where a
fraction of gross is taken as an access/recoup ceiling, the result is FLOORED.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric (int/float/Decimal) to the nearest whole cent, half up."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_fraction(amount_cents, fraction):
    """floor(amount_cents * fraction) using exact decimal arithmetic."""
    d = Decimal(str(amount_cents)) * Decimal(str(fraction))
    # floor to integer
    return int(d.to_integral_value(rounding="ROUND_FLOOR"))
