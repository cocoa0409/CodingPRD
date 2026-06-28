"""Calculation rules (SCAFFOLD §1.3 / PRD 2.5, 2.7, 3.3, 3.9, 3.11).

All money is integer cents. Constants are pinned here.
"""

import math

from common import floor_cents, round_half_up_cents

# ---- transformer_usable_capacity (PRD 2.5) ----
DERATE_PCT = 0.80

# ---- quote_pricing (PRD 3.3) ----
NIGHT_DEMO_FEE_CENTS = 15000
TAX_RATE = 0.0825  # 8.25%

# ---- service_plan_refund (PRD 3.9) ----
REFUND_GRACE_DAYS = 30

# ---- warranty_replacement_credit (PRD 3.11) ----
FULL_WINDOW_MONTHS = 12

# ---- temporal windows (PRD 2.8) ----
TRANSITION_BUFFER_MIN = 5


def usable_capacity(rated_capacity_va):
    """floor(rated_capacity_va * 0.80) — derated continuous-load budget."""
    return int(math.floor(rated_capacity_va * DERATE_PCT))


def volume_tier_pct(total_qty):
    """Volume-discount rate by combined fixture quantity. Breakpoints at
    10/25/50 fall into the higher tier (>=)."""
    if total_qty >= 50:
        return 0.15
    if total_qty >= 25:
        return 0.10
    if total_qty >= 10:
        return 0.05
    return 0.00


def quote_pricing(lines, night_demo_requested):
    """Pinned order: sum -> discount (floored on summed subtotal) -> demo fee
    -> tax (once, round-half-up on the taxable base) -> grand total.

    Returns (subtotal_cents, discount_cents, tax_cents, grand_total_cents).
    """
    subtotal_cents = sum(l["quantity"] * l["unit_price_cents"] for l in lines)
    total_qty = sum(l["quantity"] for l in lines)
    tier_pct = volume_tier_pct(total_qty)
    discount_cents = floor_cents(subtotal_cents * tier_pct)
    demo_fee_cents = NIGHT_DEMO_FEE_CENTS if night_demo_requested else 0
    taxable_base_cents = subtotal_cents - discount_cents + demo_fee_cents
    tax_cents = round_half_up_cents(taxable_base_cents * TAX_RATE)
    grand_total_cents = taxable_base_cents + tax_cents
    return subtotal_cents, discount_cents, tax_cents, grand_total_cents


def service_plan_refund(annual_fee_cents, refundable, elapsed_days):
    """Returns (variant, refund_cents).

    PRORATED when refundable OR elapsed_days <= 30:
        refund = round_half_up(annual_fee_cents * unused_days / 365)
    FORFEIT otherwise: refund = 0.
    """
    unused_days = max(0, 365 - elapsed_days)
    if refundable or elapsed_days <= REFUND_GRACE_DAYS:
        refund_cents = round_half_up_cents(annual_fee_cents * unused_days / 365)
        return "PRORATED", refund_cents
    return "FORFEIT", 0


def warranty_replacement_credit(purchase_price_cents, warranty_months, age_months):
    """Returns (variant, credit_cents). Caller has already gated
    age_months < warranty_months (ERR_OUT_OF_WARRANTY at boundary).

    FULL when age_months <= 12: credit = full purchase price.
    DEPRECIATED otherwise (12 < age < warranty_months):
        credit = round_half_up(purchase_price_cents * (warranty_months - age) / warranty_months)
    """
    if age_months <= FULL_WINDOW_MONTHS:
        return "FULL", purchase_price_cents
    remaining = warranty_months - age_months
    credit_cents = round_half_up_cents(
        purchase_price_cents * remaining / warranty_months
    )
    return "DEPRECIATED", credit_cents


def elapsed_days(now_dt, since_dt):
    """Whole days between two instants, floored."""
    delta = now_dt - since_dt
    return int(math.floor(delta.total_seconds() / 86400.0))


def age_months_30day(now_dt, installed_dt):
    """Floored 30-day months between install and now."""
    delta = now_dt - installed_dt
    return int(math.floor(delta.total_seconds() / (30 * 86400.0)))
