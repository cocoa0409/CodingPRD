"""Monetary helpers: half-up rounding to whole cents, etc."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def round_half_up_to_cent(decimal_cents: Decimal) -> int:
    """Round a Decimal cents amount half-up to a whole cent."""
    if not isinstance(decimal_cents, Decimal):
        decimal_cents = Decimal(str(decimal_cents))
    return int(decimal_cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
