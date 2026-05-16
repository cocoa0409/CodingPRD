"""Money helpers — integer cents only, round-half-up to whole cents."""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up_cents(amount):
    """Round a Decimal/int/float amount of cents to a whole-cent integer using round-half-up."""
    d = Decimal(str(amount))
    rounded = d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded)


def apply_pct(list_fee_cents, pct_str):
    """Apply a percentage (as a string like "0.10") to a cents value, round half-up to whole cents."""
    return round_half_up_cents(Decimal(list_fee_cents) * Decimal(pct_str))
