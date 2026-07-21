"""Calculation rules: pricing, points, tier, inventory, counts."""
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    TIER_DISCOUNT_PCT,
    TAX_RATE,
    POINTS_MULT,
    DISCOUNT_CAP_CENTS,
    POINTS_PER_CENT_DIVISOR,
    SILVER_THRESHOLD_CENTS,
    GOLD_THRESHOLD_CENTS,
    TIER_STANDARD,
    TIER_SILVER,
    TIER_GOLD,
)


def round_half_up(value):
    """Round a Decimal to the nearest integer, halves rounding up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_gross(line):
    return line["unit_price_cents"] * line["qty"]


def order_pricing(lines, tier, state_code):
    """order_pricing calculation. Returns (subtotal, discount, tax, total)."""
    pct = TIER_DISCOUNT_PCT[tier]
    rate = TAX_RATE[state_code]
    subtotal = sum(line_gross(l) for l in lines)
    discount = min(round_half_up(Decimal(subtotal) * pct), DISCOUNT_CAP_CENTS)
    taxable = subtotal - discount
    tax = round_half_up(Decimal(taxable) * rate)
    total = subtotal - discount + tax
    return subtotal, discount, tax, total


def loyalty_points(lines, tier):
    """loyalty_points_accrual: round PER LINE, then sum."""
    mult = POINTS_MULT[tier]
    total = 0
    for l in lines:
        contribution = (Decimal(line_gross(l)) / Decimal(POINTS_PER_CENT_DIVISOR)) * mult
        total += round_half_up(contribution)
    return total


def points_reversed(line, return_qty, tier):
    """return_refund points component (uses the order's tier snapshot)."""
    mult = POINTS_MULT[tier]
    gross = line["unit_price_cents"] * return_qty
    return round_half_up((Decimal(gross) / Decimal(POINTS_PER_CENT_DIVISOR)) * mult)


def compute_tier(annual_spend_cents):
    if annual_spend_cents >= GOLD_THRESHOLD_CENTS:
        return TIER_GOLD
    if annual_spend_cents >= SILVER_THRESHOLD_CENTS:
        return TIER_SILVER
    return TIER_STANDARD


def recompute_available(sku):
    sku["available_qty"] = max(sku["on_hand_qty"] - sku["reserved_qty"], 0)


def recompute_registered_count(cls, class_registrations):
    count = sum(
        1
        for r in class_registrations.values()
        if r["class_id"] == cls["id"] and r["status"] == "BOOKED"
    )
    cls["registered_count"] = count
    return count
