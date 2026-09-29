"""Integer-cent arithmetic. Decimal with ROUND_HALF_UP only, never float."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) -> int"""
    if denominator == 0:
        return 0
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    if denominator == 0:
        return 0
    return numerator // denominator
