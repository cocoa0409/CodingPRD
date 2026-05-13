"""Pure calculation helpers — rounding, basis-point math."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value) -> int:
    """Round a numeric value to nearest integer with half-up rounding."""
    if isinstance(value, int):
        return value
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mul_bp_round_half_up(amount_cents: int, bp: int) -> int:
    """amount * bp / 10000, half-up rounded."""
    if bp == 0 or amount_cents == 0:
        return 0
    d = (Decimal(amount_cents) * Decimal(bp)) / Decimal(10000)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mul_bp_truncate(amount_cents: int, bp: int) -> int:
    """amount * bp / 10000, truncate toward zero (integer division)."""
    if bp == 0 or amount_cents == 0:
        return 0
    return (amount_cents * bp) // 10000
