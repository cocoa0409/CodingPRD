"""Monetary helpers — Decimal with round-half-up to 2 dp."""
from decimal import Decimal, ROUND_HALF_UP


CENTS = Decimal("0.01")


def D(value):
    """Coerce a JSON number/int/str to Decimal without float artifacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        # bool is an int subclass; treat as invalid number elsewhere, but be safe
        return Decimal(int(value))
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


def round2(value):
    """Round a Decimal (or number) to 2 dp, round-half-up. Returns Decimal."""
    return D(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def money_out(value):
    """Render a money Decimal as a JSON number (float) with 2dp value.

    JSON has no decimal type; tests compare numerically. We round to 2dp first
    so the emitted float is the intended cents value.
    """
    q = round2(value)
    return float(q)
