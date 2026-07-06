"""The five calculation rules (SCAFFOLD section 1.3 / PRD sections 2.5, 3.5, 3.6).

Money is integer cents, weight integer grams. Real-valued intermediates round
half up to whole cents. Line pricing rounds PER LINE before any order summation.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

TAX_RATE = Decimal("0.08")
PLUS_DISCOUNT_FACTOR = Decimal("0.10")
LOYALTY_DIVISOR = 100
SHRINK_QUARANTINE_G = 200


def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, halves away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# C1 — dual-variant tare/weight tiered line pricing
# ---------------------------------------------------------------------------
def refill_line_price(net_g, product, membership_tier):
    if net_g >= product["bulk_tier_threshold_g"]:
        rate = product["bulk_tier_price_cents_per_100g"]
    else:
        rate = product["unit_price_cents_per_100g"]
    goods = Decimal(rate) * Decimal(net_g) / Decimal(100)
    disc = PLUS_DISCOUNT_FACTOR if membership_tier == "PLUS" else Decimal(0)
    return round_half_up(goods * (Decimal(1) - disc))


# ---------------------------------------------------------------------------
# C2 — order totals with pinned per-line-then-sum rounding
# ---------------------------------------------------------------------------
def order_totals(final_lines, products, deposit_total_cents, redeem_points):
    """final_lines: list of line dicts (FINAL, non-voided).
    products: id -> product dict (to read `taxable`).
    Returns (subtotal, discount, deposit_total, tax, total).
    """
    subtotal = sum(l["line_price_cents"] for l in final_lines)
    redeem = redeem_points if redeem_points else 0
    discount = min(redeem, subtotal)
    taxable_goods = sum(
        l["line_price_cents"] for l in final_lines if products[l["product_id"]]["taxable"]
    )
    if subtotal == taxable_goods:
        base = max(0, taxable_goods - discount)
    elif subtotal > 0:
        share = round_half_up(Decimal(discount) * Decimal(taxable_goods) / Decimal(subtotal))
        base = taxable_goods - share
    else:
        base = 0
    if base < 0:
        base = 0
    tax = round_half_up(TAX_RATE * Decimal(base))
    total = subtotal - discount + deposit_total_cents + tax
    return subtotal, discount, deposit_total_cents, tax, total


# ---------------------------------------------------------------------------
# C3 — dual-variant loyalty accrual
# ---------------------------------------------------------------------------
def loyalty_points(settled_cents, membership_tier):
    base = settled_cents // LOYALTY_DIVISOR  # floor for non-negative cents
    mult = Decimal("1.5") if membership_tier == "PLUS" else Decimal("1")
    return int((Decimal(base) * mult).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# C4 — shrink reconciliation
# ---------------------------------------------------------------------------
def shrink(last_recount_g, dispensed_g, restocked_g, physical_g):
    book_on_hand = last_recount_g - dispensed_g + restocked_g
    return book_on_hand - physical_g
