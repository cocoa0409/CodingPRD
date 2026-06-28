"""Monetary calculations (scaffold §1.3, PRD §2.9 / §3.7).

All money is integer cents. The only division+rounding is commission, which is
round_half_up applied ONCE to the single final product.
"""
from decimal import Decimal, ROUND_HALF_UP

BPS_DENOMINATOR = 10000


def order_gross_revenue(line_items_resolved):
    """sum over line items of MenuItem.price_cents * qty (integer cents).

    line_items_resolved: list of (menu_item, qty)."""
    total = 0
    for menu_item, qty in line_items_resolved:
        total += menu_item["price_cents"] * qty
    return total


def order_commission(gross_revenue_cents, commission_rate_bps):
    """round_half_up( gross * bps / 10000 ) — rounding applied ONCE to the
    single product. Uses Decimal to avoid float error."""
    product = Decimal(gross_revenue_cents) * Decimal(commission_rate_bps)
    value = product / Decimal(BPS_DENOMINATOR)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def order_food_cost(consumption_slices):
    """sum over each recorded slice of grams_taken * that lot's unit cost.
    Exact integer arithmetic (no rounding)."""
    total = 0
    for sl in consumption_slices:
        total += sl["grams"] * sl["unit_cost_cents_per_gram"]
    return total
