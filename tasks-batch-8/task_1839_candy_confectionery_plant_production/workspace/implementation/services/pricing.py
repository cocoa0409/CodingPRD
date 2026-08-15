"""Pricing and rate calculations (PRD §2.9, §3.6, §3.7, §3.8). All money is
integer cents; rounding is half-up; rework standard yield rounds down;
packaging requirements use ceiling division."""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from db import store

MIN_PRICE_FLOOR_CENTS = 50
GIFT_KIT_DISCOUNT_PCT = Decimal("0.10")
BLOOM_RELEASE_MAX_PCT = Decimal("2.00")


def ceil_div(a, b):
    """Ceiling division for packaging requirements (any fractional component
    rounds up to a whole component)."""
    return -(-a // b)


def gift_set_price(gift_product_id):
    """gift_set_price: per component line, round_half_up(base_price_cents *
    qty_per_set * (1 - 0.10)) to a whole cent, then integer sum. Rounding
    order is pinned: round each component line first, then sum."""
    total = 0
    for gc in store.gift_components.values():
        if gc["gift_product_id"] != gift_product_id:
            continue
        comp = store.products[gc["component_product_id"]]
        line = (Decimal(comp["base_price_cents"]) * Decimal(gc["qty_per_set"])
                * (Decimal(1) - GIFT_KIT_DISCOUNT_PCT))
        total += int(line.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total


def markdown_unit_price(base_price_cents, discount_pct):
    """markdown_price: raw = base * (1 - discount_pct); round half-up to a
    whole cent; then apply the 50-cent floor."""
    raw = Decimal(base_price_cents) * (Decimal(1) - Decimal(str(discount_pct)))
    cents = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(cents, MIN_PRICE_FLOOR_CENTS)


def defect_rate_pct(affected_units, lot_qty_at_open):
    """bloom_defect_rate: round_half_up(100 * affected / at_open, 2)."""
    if lot_qty_at_open <= 0:
        return 0.0
    v = (Decimal(100 * affected_units) / Decimal(lot_qty_at_open)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(v)


def expected_rework_output(rework_qty, standard_yield_pct):
    """rework_yield standard variant: floor(rework_qty * standard_yield_pct)."""
    v = Decimal(rework_qty) * Decimal(str(standard_yield_pct))
    return int(v.to_integral_value(rounding=ROUND_FLOOR))
