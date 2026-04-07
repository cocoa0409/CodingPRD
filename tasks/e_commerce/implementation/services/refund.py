"""Refund lifecycle service."""

import db
from errors import (
    ERR_ORDER_NOT_FOUND,
    ERR_ORDER_NOT_PAID,
    ERR_ORDER_ITEM_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_REFUND_EXCEEDS_REMAINING,
    ERR_REFUND_EXCEEDS_ORDER_TOTAL,
    ERR_REFUND_NOT_APPROVED,
    ERR_REFUND_NOT_FOUND,
    ERR_REFUND_NOT_REQUESTED,
    raise_error,
)
from money import round_money
from services.commission import calculate_commission
from services.shop import get_shop


def _get_order(order_id):
    order = db.find_one("orders", id=order_id)
    if not order:
        raise_error(ERR_ORDER_NOT_FOUND, f"Order {order_id} not found.")
    return order


def _get_refund(order_id, refund_id):
    refund = db.find_one("refunds", id=refund_id, order_id=order_id)
    if not refund:
        raise_error(ERR_REFUND_NOT_FOUND, f"Refund {refund_id} not found.")
    return refund


def _processed_refund_total(order_id):
    """Sum of all previously processed refund amounts for an order."""
    refunds = db.find_many("refunds", order_id=order_id, status="PROCESSED")
    return round_money(sum(r.get("refund_amount", 0) for r in refunds))


# ---------------------------------------------------------------------------
# create_refund
# ---------------------------------------------------------------------------

def create_refund(order_id, data, customer_id):
    """Request a refund for a paid order."""
    order = _get_order(order_id)

    if order["payment_status"] not in ("PAID", "PARTIAL_REFUND"):
        raise_error(ERR_ORDER_NOT_PAID, "Order must be paid to request a refund.")

    refund_type = data.get("refund_type", "FULL")
    if refund_type not in ("FULL", "PARTIAL"):
        raise_error(ERR_INVALID_REQUEST, "refund_type must be FULL or PARTIAL.")

    refund_items = data.get("refund_items") or data.get("items") or []
    reason = data.get("reason", "")

    # Validate order items exist and quantities don't exceed remaining
    order_items = db.find_many("order_items", order_id=order_id)
    oi_map = {oi["id"]: oi for oi in order_items}
    # Also build a map by product_id for backwards compatibility
    oi_by_product = {oi["product_id"]: oi for oi in order_items}

    if refund_type == "PARTIAL" and refund_items:
        # Gather already-approved/processed refund quantities
        all_refunds = db.find_many("refunds", order_id=order_id)
        refunded_qty = {}
        for r in all_refunds:
            if r["status"] in ("REQUESTED", "APPROVED", "PROCESSED"):
                for ri in (r.get("refund_items") or r.get("items") or []):
                    pid = ri.get("order_item_id") or ri.get("product_id")
                    refunded_qty[pid] = refunded_qty.get(pid, 0) + ri.get("quantity", 0)

        for ri in refund_items:
            item_id = ri.get("order_item_id") or ri.get("product_id")
            oi = oi_map.get(item_id) or oi_by_product.get(item_id)
            if not oi:
                raise_error(ERR_ORDER_ITEM_NOT_FOUND, f"Order item {item_id} not found.")
            already = refunded_qty.get(item_id, 0)
            if already + ri.get("quantity", 0) > oi["quantity"]:
                raise_error(
                    ERR_REFUND_EXCEEDS_REMAINING,
                    f"Refund quantity for item {item_id} exceeds remaining.",
                )

    refund = db.insert("refunds", {
        "order_id": order_id,
        "shop_id": order["shop_id"],
        "customer_id": customer_id,
        "refund_type": refund_type,
        "status": "REQUESTED",
        "reason": reason,
        "refund_items": refund_items,
        "items": refund_items,
        "refund_amount": 0.0,
        "refund_subtotal": 0.0,
        "refund_discount_share": 0.0,
        "inventory_restored": False,
    })
    return refund


# ---------------------------------------------------------------------------
# approve_refund
# ---------------------------------------------------------------------------

def approve_refund(order_id, refund_id):
    """Approve a requested refund (validate quantities)."""
    order = _get_order(order_id)
    refund = _get_refund(order_id, refund_id)

    if refund["status"] != "REQUESTED":
        raise_error(ERR_REFUND_NOT_REQUESTED, "Refund is not in REQUESTED state.")

    # Validate quantities don't exceed remaining
    refund_items = refund.get("refund_items") or refund.get("items") or []
    order_items = db.find_many("order_items", order_id=order_id)
    oi_by_id = {oi["id"]: oi for oi in order_items}
    oi_by_product = {oi["product_id"]: oi for oi in order_items}

    # Gather already-approved/processed refund quantities
    all_refunds = db.find_many("refunds", order_id=order_id)
    refunded_qty = {}
    for r in all_refunds:
        if r["id"] == refund_id:
            continue
        if r["status"] in ("APPROVED", "PROCESSED"):
            for ri in (r.get("refund_items") or r.get("items") or []):
                item_key = ri.get("order_item_id") or ri.get("product_id")
                refunded_qty[item_key] = refunded_qty.get(item_key, 0) + ri.get("quantity", 0)

    for ri in refund_items:
        item_key = ri.get("order_item_id") or ri.get("product_id")
        oi = oi_by_id.get(item_key) or oi_by_product.get(item_key)
        if not oi:
            continue
        already = refunded_qty.get(item_key, 0)
        if already + ri.get("quantity", 0) > oi["quantity"]:
            raise_error(
                ERR_REFUND_EXCEEDS_REMAINING,
                f"Refund quantity for item {item_key} exceeds remaining.",
            )

    db.update("refunds", refund_id, {"status": "APPROVED"})
    return db.find_one("refunds", id=refund_id)


# ---------------------------------------------------------------------------
# reject_refund
# ---------------------------------------------------------------------------

def reject_refund(order_id, refund_id):
    """Reject a requested refund."""
    _get_order(order_id)
    refund = _get_refund(order_id, refund_id)

    if refund["status"] != "REQUESTED":
        raise_error(ERR_REFUND_NOT_REQUESTED, "Refund is not in REQUESTED state.")

    db.update("refunds", refund_id, {"status": "REJECTED"})
    return db.find_one("refunds", id=refund_id)


# ---------------------------------------------------------------------------
# process_refund
# ---------------------------------------------------------------------------

def process_refund(order_id, refund_id):
    """Process an approved refund: calculate amount, restore inventory, reverse commission."""
    order = _get_order(order_id)
    refund = _get_refund(order_id, refund_id)

    if refund["status"] != "APPROVED":
        raise_error(ERR_REFUND_NOT_APPROVED, "Refund is not in APPROVED state.")

    order_items = db.find_many("order_items", order_id=order_id)
    already_refunded = _processed_refund_total(order_id)
    order_total = order["total_amount"]

    # Build lookup maps for order items
    oi_by_id = {oi["id"]: oi for oi in order_items}
    oi_by_product = {oi["product_id"]: oi for oi in order_items}

    # --- Calculate refund amount ---
    refund_subtotal = 0.0
    refund_discount_share = 0.0

    if refund["refund_type"] == "FULL":
        refund_subtotal = round_money(order.get("subtotal", order_total))
        refund_discount_share = round_money(order.get("discount_amount", 0.0))
        refund_amount = round_money(order_total - already_refunded)
    else:
        # PARTIAL: proportional with discount allocation
        refund_items_data = refund.get("refund_items") or refund.get("items") or []
        subtotal = order.get("subtotal", order_total)
        discount_total = order.get("discount_amount", 0.0)

        for ri in refund_items_data:
            item_key = ri.get("order_item_id") or ri.get("product_id")
            oi = oi_by_id.get(item_key) or oi_by_product.get(item_key)
            if not oi:
                continue
            qty = ri.get("quantity", 0)
            line_value = round_money(oi["unit_price"] * qty)
            refund_subtotal = round_money(refund_subtotal + line_value)

            # Proportional discount share
            if subtotal > 0:
                proportion = line_value / subtotal
                share = round_money(discount_total * proportion)
            else:
                share = 0.0
            refund_discount_share = round_money(refund_discount_share + share)

        refund_amount = round_money(refund_subtotal - refund_discount_share)

    # Cap at remaining
    remaining = round_money(order_total - already_refunded)
    if refund_amount > remaining:
        refund_amount = remaining

    # --- Create refund payment ---
    db.insert("payments", {
        "order_id": order_id,
        "type": "REFUND",
        "status": "SUCCESS",
        "amount": refund_amount,
    })

    # --- Restore inventory ---
    refund_items_for_inventory = refund.get("refund_items") or refund.get("items") or []
    if refund["refund_type"] == "FULL":
        # Restore all order items
        for oi in order_items:
            product = db.find_one("products", id=oi["product_id"])
            if product:
                new_inv = product.get("inventory_count", 0) + oi["quantity"]
                db.update("products", product["id"], {
                    "inventory_count": new_inv,
                    "available_count": new_inv - product.get("reserved_count", 0),
                })
    else:
        for ri in refund_items_for_inventory:
            item_key = ri.get("order_item_id") or ri.get("product_id")
            oi = oi_by_id.get(item_key) or oi_by_product.get(item_key)
            if not oi:
                continue
            product = db.find_one("products", id=oi["product_id"])
            if product:
                new_inv = product.get("inventory_count", 0) + ri.get("quantity", 0)
                db.update("products", product["id"], {
                    "inventory_count": new_inv,
                    "available_count": new_inv - product.get("reserved_count", 0),
                })

    # --- Update order payment status ---
    total_refunded = round_money(already_refunded + refund_amount)
    if total_refunded >= order_total:
        new_payment_status = "FULL_REFUND"
    else:
        new_payment_status = "PARTIAL_REFUND"

    db.update("orders", order_id, {"payment_status": new_payment_status})

    # --- Reverse proportional commission from settlement ---
    shop = get_shop(order["shop_id"])
    commission_rate = order.get("commission_rate", 0.0)
    commission_reversal = round_money(refund_amount * commission_rate)
    seller_reversal = round_money(refund_amount - commission_reversal)

    new_balance = round_money(shop.get("settlement_balance", 0.0) - seller_reversal)
    new_gmv = round_money(shop.get("monthly_gmv", 0.0) - refund_amount)
    db.update("shops", shop["id"], {
        "settlement_balance": new_balance,
        "monthly_gmv": new_gmv,
    })

    db.update("refunds", refund_id, {
        "status": "PROCESSED",
        "refund_subtotal": refund_subtotal,
        "refund_discount_share": refund_discount_share,
        "refund_amount": refund_amount,
        "inventory_restored": True,
    })

    return db.find_one("refunds", id=refund_id)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_refund(order_id, refund_id):
    return _get_refund(order_id, refund_id)


def list_refunds(order_id, limit, offset):
    return db.find("refunds", filters={"order_id": order_id}, limit=limit, offset=offset)
