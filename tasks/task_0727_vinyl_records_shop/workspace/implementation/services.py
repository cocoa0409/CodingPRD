"""Shared business logic: recomputes, cascades, and serialization."""
import db
from models import touch
import calculations as calc


# ---------------------------------------------------------------------------
# Serialization: strip nothing; entities are stored as plain dicts already.
# ---------------------------------------------------------------------------
def public(entity):
    return dict(entity) if entity is not None else None


def public_list(entities):
    return [dict(e) for e in entities]


# ---------------------------------------------------------------------------
# Customer / loyalty
# ---------------------------------------------------------------------------
def recompute_tier(customer):
    customer["loyalty_tier"] = calc.loyalty_tier(customer["loyalty_points"])


# ---------------------------------------------------------------------------
# Inventory pricing
# ---------------------------------------------------------------------------
def compute_item_price(item):
    product = db.db.products[item["product_id"]]
    consignment_list = None
    if item.get("consignment_id"):
        cons = db.db.consignments.get(item["consignment_id"])
        if cons is not None:
            consignment_list = cons["list_price_cents"]
    return calc.item_list_price(
        product["base_price_cents"],
        item["condition_grade"],
        item["is_used"],
        consignment_list,
    )


# ---------------------------------------------------------------------------
# Order totals
# ---------------------------------------------------------------------------
def recompute_order(order):
    lines = [
        l for l in db.db.order_lines.values() if l["order_id"] == order["id"]
    ]
    line_inputs = []
    for l in lines:
        item = db.db.inventory_items.get(l["inventory_item_id"])
        is_used = bool(item["is_used"]) if item else False
        line_inputs.append({
            "unit_price_cents": l["unit_price_cents"],
            "qty": l["qty"],
            "is_used": is_used,
        })
    customer = db.db.customers[order["customer_id"]]
    subtotal, discount, shipping, total = calc.order_totals(
        line_inputs, order["channel"], customer["loyalty_tier"]
    )
    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["shipping_cents"] = shipping
    order["total_cents"] = total


# ---------------------------------------------------------------------------
# InventoryItem release (order cancel): AVAILABLE, or ON_DISPLAY if consigned
# and its Consignment still ACTIVE.
# ---------------------------------------------------------------------------
def release_item(item):
    item["hold_start_at"] = None
    item["hold_end_at"] = None
    if item.get("consignment_id"):
        cons = db.db.consignments.get(item["consignment_id"])
        if cons is not None and cons["status"] == "ACTIVE":
            item["status"] = "ON_DISPLAY"
            touch(item)
            return
    item["status"] = "AVAILABLE"
    touch(item)


# ---------------------------------------------------------------------------
# Waitlist promotion: earliest-created WAITLISTED pre-order for a product.
# Called after a unit frees up on an allocation.
# ---------------------------------------------------------------------------
def promote_waitlist(allocation):
    if allocation["available_count"] < 1:
        return
    candidates = [
        p for p in db.db.pre_orders.values()
        if p["allocation_id"] == allocation["id"] and p["status"] == "WAITLISTED"
    ]
    if not candidates:
        return
    candidates.sort(key=lambda x: (x["created_at"], x["id"]))
    winner = candidates[0]
    winner["status"] = "RESERVED"
    touch(winner)
    allocation["available_count"] -= 1
    allocation["reserved_count"] += 1
    touch(allocation)


# ---------------------------------------------------------------------------
# Consignment sale settlement (fired by order ship/fulfill on a consigned copy).
# ---------------------------------------------------------------------------
def settle_consignment_sale(item, order_line):
    if not item.get("consignment_id"):
        return
    cons = db.db.consignments.get(item["consignment_id"])
    if cons is None or cons["status"] != "ACTIVE":
        return
    cons["sale_price_cents"] = order_line["unit_price_cents"]
    cons["status"] = "SOLD"
    cons["actual_payout_cents"] = calc.consignment_payout(cons["sale_price_cents"])
    consignor = db.db.customers.get(cons["consignor_id"])
    if consignor is not None:
        consignor["store_credit_cents"] += cons["actual_payout_cents"]
        touch(consignor)
    cons["display_slot_id"] = None
    touch(cons)


# ---------------------------------------------------------------------------
# Consignment expiry sweep: ACTIVE past display_end -> EXPIRED.
# ---------------------------------------------------------------------------
def sweep_consignment(cons):
    if cons["status"] != "ACTIVE":
        return
    if cons.get("display_end") is None:
        return
    end = db.parse_iso(cons["display_end"])
    if db.db.now > end:
        cons["status"] = "EXPIRED"
        item = _linked_item(cons)
        if item is not None and item["status"] != "SOLD":
            item["status"] = "AVAILABLE"
            item["hold_start_at"] = None
            item["hold_end_at"] = None
            touch(item)
        cons["display_slot_id"] = None
        touch(cons)


def _linked_item(cons):
    for it in db.db.inventory_items.values():
        if it.get("consignment_id") == cons["id"]:
            return it
    return None


# ---------------------------------------------------------------------------
# Regrade cascade (§3.8).
# ---------------------------------------------------------------------------
def regrade_cascade(item, resolution_grade):
    item["condition_grade"] = resolution_grade
    item["list_price_cents"] = compute_item_price(item)
    touch(item)
    # Resync any OrderLine on an open order (PENDING/RESERVED).
    for line in db.db.order_lines.values():
        if line["inventory_item_id"] != item["id"]:
            continue
        order = db.db.orders.get(line["order_id"])
        if order is None:
            continue
        if order["fulfillment_status"] in ("PENDING", "RESERVED"):
            line["unit_price_cents"] = item["list_price_cents"]
            touch(line)
            recompute_order(order)
            touch(order)
