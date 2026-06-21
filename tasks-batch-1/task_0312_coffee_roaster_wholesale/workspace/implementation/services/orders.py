"""Order creation + fulfillment bubble-up shared logic."""
from helpers import new_record
from db import store
from services.inventory import price_order


def build_order(account, lines_with_products, standing_order_id=None):
    """Create and store an Order priced against the account's tier.

    lines_with_products: list of {product_id, qty_kg, product}.
    Returns the stored order record.
    """
    tier = store.price_tiers[account["price_tier_id"]]
    subtotal, discount, total = price_order(
        [{"product": l["product"], "qty_kg": l["qty_kg"]} for l in lines_with_products],
        tier,
    )
    rec = new_record()
    rec.update({
        "account_id": account["id"],
        "standing_order_id": standing_order_id,
        "lines": [{"product_id": l["product_id"], "qty_kg": l["qty_kg"]} for l in lines_with_products],
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "total_cents": total,
        "fulfillment_status": "OPEN",
        "billing_status": "UNBILLED",
    })
    store.orders[rec["id"]] = rec
    return rec


def shipped_kg_for_product(order, product_id):
    """Sum of allocated_kg over SHIPPED fulfillments of `order` for product_id."""
    total = 0.0
    for f in store.fulfillments.values():
        if f["order_id"] == order["id"] and f["product_id"] == product_id and f["status"] == "SHIPPED":
            total += f["allocated_kg"]
    return total


def active_alloc_kg_for_product(order, product_id):
    """Sum of allocated_kg over RESERVED+SHIPPED fulfillments for a product line."""
    total = 0.0
    for f in store.fulfillments.values():
        if f["order_id"] == order["id"] and f["product_id"] == product_id and f["status"] in ("RESERVED", "SHIPPED"):
            total += f["allocated_kg"]
    return total


def derive_fulfillment_status(order):
    """Bubble-up fulfillment_status from SHIPPED children (PRD §3.5).

    Terminal states (FULFILLED, CANCELLED) are never overwritten here.
    """
    if order["fulfillment_status"] in ("FULFILLED", "CANCELLED"):
        return order["fulfillment_status"]

    from decimal import Decimal as Dc

    all_covered = True
    any_shipped = False
    for line in order["lines"]:
        shipped = Dc(str(shipped_kg_for_product(order, line["product_id"])))
        ordered = Dc(str(line["qty_kg"]))
        if shipped > 0:
            any_shipped = True
        if shipped < ordered:
            all_covered = False

    if all_covered:
        return "FULFILLED"
    if any_shipped:
        return "PARTIALLY_FULFILLED"
    return order["fulfillment_status"]  # stays OPEN
