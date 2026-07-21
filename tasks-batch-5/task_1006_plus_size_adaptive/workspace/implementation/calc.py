"""Money / rounding helpers."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric value to a whole integer, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of(amount_cents, pct_str):
    """round_half_up(amount_cents * pct) using exact decimals."""
    return round_half_up(Decimal(int(amount_cents)) * Decimal(str(pct_str)))
