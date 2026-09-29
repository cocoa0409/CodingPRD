"""Integer arithmetic discipline (PRD 2.6).

Money is whole cents, lengths are whole millimetres, rates are integer basis
points.  No float ever enters a stored or returned value.
"""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(numerator, denominator=1):
    """Round half away from zero to a whole integer.

    Decimal's ROUND_HALF_UP is 'half away from zero', which is exactly what the
    PRD asks for: an offset of -50 hundredths becomes a shift of -1 step.
    """
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    """Floor division (truncation toward negative infinity)."""
    if denominator == 0:
        return 0
    return numerator // denominator


def bp_rate(count, total):
    """count * 10000 / total, floored; 0 when total is 0."""
    if total == 0:
        return 0
    return floor_div(count * 10000, total)


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
