"""Order total computation at submit (SCAFFOLD §1.3 order_total, PRD §3.7).

subtotal -> volume discount (subtotal-level, rounded once) -> merchandise ->
free-ship-or-flat shipping -> total.
"""
import db
from common import (
    FLAT_SHIP_CENTS,
    FREE_SHIP_THRESHOLD,
    TIER1_PCT,
    TIER1_THRESHOLD,
    TIER2_PCT,
    TIER2_THRESHOLD,
    round_half_up,
)


def lines_for_order(order_id):
    return [l for l in db.order_lines.values() if l["photo_order_id"] == order_id]


def compute_order_total(order):
    """Finalize money fields on the order in place (does not bump version)."""
    lines = lines_for_order(order["id"])
    subtotal = sum(l["unit_price_cents"] * l["quantity"] for l in lines)

    if subtotal >= TIER2_THRESHOLD:
        discount_pct = TIER2_PCT
    elif subtotal >= TIER1_THRESHOLD:
        discount_pct = TIER1_PCT
    else:
        discount_pct = 0

    discount_cents = round_half_up(subtotal * discount_pct) if discount_pct else 0
    merchandise = subtotal - discount_cents
    shipping = 0 if merchandise >= FREE_SHIP_THRESHOLD else FLAT_SHIP_CENTS
    total = merchandise + shipping

    order["subtotal_cents"] = subtotal
    order["discount_pct"] = float(discount_pct)
    order["discount_cents"] = discount_cents
    order["merchandise_cents"] = merchandise
    order["shipping_cents"] = shipping
    order["total_cents"] = total
