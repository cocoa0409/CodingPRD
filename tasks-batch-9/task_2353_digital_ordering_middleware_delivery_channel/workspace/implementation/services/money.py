"""Integer-cent arithmetic with half-up rounding (PRD 2.6)."""
from decimal import Decimal, ROUND_HALF_UP

from services.constants import BPS_DENOMINATOR


def round_half_up(numerator, denominator=1):
    """Exact rational division rounded half up to a whole integer."""
    value = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def apply_bps(amount_cents, bps):
    """round_half_up(amount * bps / 10000)."""
    return round_half_up(int(amount_cents) * int(bps), BPS_DENOMINATOR)
