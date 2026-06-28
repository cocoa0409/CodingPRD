"""Calculation rules (PRD §2.7 + §3.5/§3.7, SCAFFOLD §1.3).

All monetary results are whole-cent integers. Multiplicative discounts use
round-half-up (away from zero), implemented with Decimal to avoid float error.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- ad_pricing ----
AD_SIZE_PRICE_CENTS = {"FULL": 40000, "HALF": 24000, "QUARTER": 14000}

# ---- presale_price ----
EARLY_BASE_CENTS = 6500
STANDARD_BASE_CENTS = 8000
STAMP_FEE_CENTS = 500
BULK_QTY_THRESHOLD = 5
BULK_DISCOUNT_PCT = Decimal("0.10")

# ---- production_cost ----
BASE_PAGE_ALLOWANCE = 96
PAGES_PER_SIGNATURE = 4
SIGNATURE_SURCHARGE_CENTS = 800


def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, half away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ad_pricing(size, discount_pct):
    """list_price by size tier; net = round_half_up(list * (1 - discount)) in ONE step.

    Do NOT round the list price beforehand; single rounding on the discounted amount.
    """
    list_price_cents = AD_SIZE_PRICE_CENTS[size]
    # apply discount to the integer list price, single rounding step
    raw = Decimal(list_price_cents) * (Decimal("1") - Decimal(str(discount_pct)))
    net_price_cents = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return list_price_cents, net_price_cents


def presale_price(price_tier, personalize, quantity):
    """Tier base + optional per-copy stamp fee, then bulk discount for qty >= 5.

    bulk discount = round_half_up(gross * 0.10) only when quantity >= 5.
    """
    base_cents = EARLY_BASE_CENTS if price_tier == "EARLY" else STANDARD_BASE_CENTS
    stamp_cents = STAMP_FEE_CENTS if personalize else 0
    per_copy = base_cents + stamp_cents
    gross = per_copy * quantity
    if quantity >= BULK_QTY_THRESHOLD:
        discount = int((Decimal(gross) * BULK_DISCOUNT_PCT).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        discount = 0
    total_price_cents = gross - discount
    return total_price_cents


def per_copy_cost(unit_cost_cents, target_page_count):
    """unit_cost + non-linear page surcharge (per extra 4-page signature beyond 96)."""
    surcharge_per_copy = 0
    if target_page_count > BASE_PAGE_ALLOWANCE:
        extra_signatures = math.ceil(
            (target_page_count - BASE_PAGE_ALLOWANCE) / PAGES_PER_SIGNATURE)
        surcharge_per_copy = extra_signatures * SIGNATURE_SURCHARGE_CENTS
    return unit_cost_cents + surcharge_per_copy


def production_cost(unit_cost_cents, target_page_count, quantity):
    """Exact integer arithmetic: per_copy_cost * quantity."""
    return per_copy_cost(unit_cost_cents, target_page_count) * quantity
