"""Decimal money / ratio helpers (PRD section 2.5)."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

CENT = Decimal("1")
FOUR_DP = Decimal("0.0001")
TWO_DP = Decimal("0.01")


def round_half_up_cents(x):
    return int(Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP))


def floor_cents(x):
    return int(Decimal(x).quantize(CENT, rounding=ROUND_FLOOR))


def round_half_up_4dp(x):
    return Decimal(x).quantize(FOUR_DP, rounding=ROUND_HALF_UP)


def round_half_up_2dp(x):
    return Decimal(x).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def ratio_to_float(d):
    """Serialize a 4dp Decimal ratio as a JSON number."""
    if d is None:
        return None
    return float(d)
