"""Money/precision helpers. Always integer cents; round half-up to nearest cent."""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value) -> int:
    """Round a Decimal/float/int half-up to the nearest integer cent."""
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    # fall back: convert to Decimal via repr to avoid float-binary surprises
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def proportional_share(numer_cents: int, denom_cents: int, total_cents: int) -> int:
    """Return round_half_up( total_cents * numer_cents / denom_cents ). All ints."""
    if denom_cents == 0:
        return 0
    return round_half_up(Decimal(total_cents) * Decimal(numer_cents) / Decimal(denom_cents))
