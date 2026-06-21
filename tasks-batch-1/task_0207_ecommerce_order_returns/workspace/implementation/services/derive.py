"""Derived-field computation (PRD §2.5, §3). These are pure functions of the
underlying rows; computed on read so the response always reflects current
facts. backordered_qty is the exception — it is a snapshot frozen at checkout
and stored directly on the OrderLine."""
from db import db
from services.calc import compute_return_risk


# ---- Inventory ----------------------------------------------------------

def inventory_reserved_qty(product_id, warehouse_id):
    # Only HELD reservations reduce availability. A COMMITTED reservation has
    # already physically decremented on_hand_qty at ship time, so counting it
    # again would double-subtract (the test suite asserts available_qty == 6
    # after committing 4 of 10: on_hand 6, no remaining HELD reservation).
    total = 0
    for r in db.reservations.values():
        if r["product_id"] == product_id and r["warehouse_id"] == warehouse_id \
                and r["status"] == "HELD":
            total += r["qty"]
    return total


def inventory_available_qty(item):
    reserved = inventory_reserved_qty(item["product_id"], item["warehouse_id"])
    return max(0, item["on_hand_qty"] - reserved)


# ---- OrderLine ----------------------------------------------------------

def order_line_reserved_qty(order_line_id):
    total = 0
    for r in db.reservations.values():
        if r["order_line_id"] == order_line_id and r["status"] in ("HELD", "COMMITTED"):
            total += r["qty"]
    return total


def order_line_shipped_qty(order_line_id):
    total = 0
    for sl in db.shipment_lines.values():
        if sl["order_line_id"] != order_line_id:
            continue
        ship = db.shipments.get(sl["shipment_id"])
        if ship and ship["status"] in ("SHIPPED", "DELIVERED"):
            total += sl["qty"]
    return total


def order_line_returned_qty(order_line_id):
    total = 0
    for rl in db.return_lines.values():
        if rl["order_line_id"] != order_line_id:
            continue
        rma = db.return_authorizations.get(rl["return_authorization_id"])
        if rma and rma["status"] in ("APPROVED", "REFUNDED", "EXCHANGED", "RESTOCKED"):
            total += rl["return_qty"]
    return total


# ---- Customer ledgers ---------------------------------------------------

def customer_store_credit_cents(customer_id):
    total = 0
    for e in db.credit_ledger_entries.values():
        if e["customer_id"] == customer_id:
            total += e["amount_cents"]
    return total


# Payment states that imply the order was captured at some point and therefore
# contributes to the customer's lifetime purchases. Capture is a one-way
# lifetime event: once captured, an order keeps counting even after it bubbles
# to PARTIALLY_REFUNDED / REFUNDED (the test suite asserts lifetime_purchased
# stays equal to captured_total after a refund settles). Carts and voided
# orders never contribute.
PURCHASED_STATES = ("CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED")


def customer_lifetime_purchased_cents(customer_id):
    total = 0
    for o in db.orders.values():
        if o["customer_id"] == customer_id and o["payment_status"] in PURCHASED_STATES:
            total += o["captured_total_cents"]
    return total


def customer_lifetime_refunded_cents(customer_id):
    total = 0
    for r in db.refunds.values():
        if r["customer_id"] == customer_id and r["status"] == "SETTLED":
            total += r["amount_cents"]
    return total


def customer_return_risk_score(customer_id):
    purchased = customer_lifetime_purchased_cents(customer_id)
    refunded = customer_lifetime_refunded_cents(customer_id)
    return compute_return_risk(purchased, refunded)
