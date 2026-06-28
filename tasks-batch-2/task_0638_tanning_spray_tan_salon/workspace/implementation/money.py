"""Monetary helpers (PRD §2.5).

All amounts are integer cents. Division (monthly->daily) is rounded half up to
whole cents using Decimal. Never use float for money.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) to a whole integer."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


def line_total(unit_price_cents, quantity, discount_pct):
    """round_half_up(unit_price * quantity * (1 - discount)) -> integer cents.

    discount_pct is a fractional number (e.g. 0.10). Computed with Decimal so
    per-line rounding is exact (PRD §3.8 retail order total).
    """
    raw = Decimal(unit_price_cents) * Decimal(quantity) * (Decimal(1) - Decimal(str(discount_pct)))
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
