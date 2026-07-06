"""Pure calculation helpers. Integer-cents arithmetic, ceil/floor per PRD §2.6."""
import math

# Category-tiered platform fee in basis-points. PRD §3.6.
CATEGORY_FEE_BPS = {
    "APPAREL": 1500,
    "DRINKWARE": 1200,
    "ACCESSORY": 1000,
    "PRINT": 800,
}

DOMESTIC_SHIPPING_CENTS = 599
CROSS_BORDER_SHIPPING_CENTS = 1599

STRIKE_THRESHOLD = 5

REASON_WEIGHTS = {
    "DAMAGED": 1,
    "WRONG_SIZE": 2,
    "MISPRINT": 0,
    "OTHER": 1,
    # LATE is not in weight table per PRD §3.8; not counted for strikes.
    "LATE": 0,
}


def base_per_unit(product, variant):
    return int(product["base_cost_cents"]) + int(variant.get("base_cost_delta_cents", 0) or 0)


def ceil_div(numerator, denom):
    """Integer ceiling division for positive quantities."""
    return -(-numerator // denom)


def listing_price_cents(product, variant, storefront, is_sample=False):
    """Per-PRD §3.6 tiered listed price.

    listed_price = base + ceil(base * fee_bps / 10000) + ceil(base * markup_bps / 10000)

    For sample orders: listed_price = base (no fee, no markup).
    """
    base = base_per_unit(product, variant)
    if is_sample:
        return base
    fee_bps = CATEGORY_FEE_BPS[product["category"]]
    platform_fee = ceil_div(base * fee_bps, 10000)
    markup_bps = int(storefront["markup_bps"])
    creator_markup = ceil_div(base * markup_bps, 10000)
    return base + platform_fee + creator_markup


def per_unit_creator_markup_cents(base, storefront_markup_bps):
    """ceil(base * markup_bps / 10000)"""
    return ceil_div(base * int(storefront_markup_bps), 10000)


def partner_charge_cents(base_per_unit_val, item_count, cost_multiplier_bps):
    """PRD §3.7 routing: ceil(base_per_unit * item_count * mult_bps / 10000)."""
    return ceil_div(base_per_unit_val * int(item_count) * int(cost_multiplier_bps), 10000)


def reprint_surcharge_partner_charge(initial_charge, reprint_generation):
    """PRD §3.8 consumer-fault reprint charge:
    initial + ceil(initial * 0.25 * reprint_generation).
    """
    if reprint_generation <= 0:
        return initial_charge
    # 25% surcharge scaled linearly with generation.
    surcharge = ceil_div(initial_charge * 25 * reprint_generation, 100)
    return initial_charge + surcharge


def backlog_delta(item_count):
    """ceil(item_count * 0.5) — half-hour per unit backlog delta."""
    return math.ceil(int(item_count) * 0.5)


def floor_fee(gross_earnings_cents, fee_bps):
    """floor(gross * fee_bps / 10000). PRD §3.9 uses floor for fees."""
    return (gross_earnings_cents * int(fee_bps)) // 10000
