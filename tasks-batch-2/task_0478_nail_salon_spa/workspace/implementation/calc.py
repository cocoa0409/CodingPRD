"""Monetary calculations with integer-cent precision and explicit rounding
(PRD §2.7, §3.10, §3.11, §3.16). Never uses float for money.
"""
import math
from decimal import Decimal, ROUND_HALF_UP


def round_half_up_cents(amount):
    """Round a Decimal/number of cents half-up to a whole integer cent (PRD §2.7)."""
    d = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def commission_earning_cents(subtotal_cents, commission_pct):
    """Per-line technician earning for a COMMISSION tech (PRD §3.11):
    round_half_up(subtotal * (1 - commission_pct))."""
    keep_fraction = Decimal("1") - Decimal(str(commission_pct))
    product = Decimal(subtotal_cents) * keep_fraction
    return round_half_up_cents(product)


def commission_aggregate_payout_cents(gross_service_cents, commission_pct):
    """Statement payout for a COMMISSION tech (PRD §3.16): SUM-THEN-ROUND —
    aggregate the gross first, then apply (1 - commission_pct) once, half-up.
    Deliberately differs from the per-line round of §3.11."""
    keep_fraction = Decimal("1") - Decimal(str(commission_pct))
    product = Decimal(gross_service_cents) * keep_fraction
    return round_half_up_cents(product)


def ceil_points(loyalty_applied_cents, point_value_cents):
    """Points consumed = ceil(loyalty_applied_cents / point_value_cents) (PRD §2.7,
    §3.10): any partial point needed to cover a cent amount consumes a full point."""
    if loyalty_applied_cents <= 0:
        return 0
    return math.ceil(loyalty_applied_cents / point_value_cents)
