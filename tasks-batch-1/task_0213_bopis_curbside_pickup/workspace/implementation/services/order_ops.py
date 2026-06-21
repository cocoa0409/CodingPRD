"""Order fulfillment + payment state machine side effects (PRD §3.3-§3.9)."""

from db import db, stamp_common, stamp_ledger, touch
from clock import add_minutes, parse_iso
from services import inventory as inv_svc
from services import money
from services.derived import recompute_slot_fill, recompute_pickup_standing, hold_of


def lines_of(order_id):
    return [ln for ln in db.order_lines.values() if ln["order_id"] == order_id]


def _slot_release(order, reason_order_id):
    """Release the booked slot: booked_count -= 1, recompute fill, bump version."""
    slot = db.pickup_slots.get(order.get("slot_id"))
    if slot is not None and slot["booked_count"] > 0:
        slot["booked_count"] -= 1
        recompute_slot_fill(slot)
        touch(slot)


# --- Cancellation cascades --------------------------------------------------

def cancel_submitted(order):
    """SUBMITTED -> CANCELLED: release reservations, drop slot, full refund."""
    reason = "ORDER:%s" % order["id"]
    for line in lines_of(order["id"]):
        if line["qty_reserved"] > 0:
            inv = inv_svc.find_inventory(order["store_id"], line["product_id"])
            if inv is not None:
                inv_svc.release(inv, line["qty_reserved"], reason)
        line["qty_reserved"] = 0
        line["line_status"] = "NOT_FULFILLED"
        touch(line)
    _slot_release(order, order["id"])
    order["refunded_total_cents"] = order["authorized_total_cents"]
    order["payment_status"] = "REFUNDED"


def cancel_picking(order):
    """PICKING -> CANCELLED: restock picked units, release reservations, full refund."""
    reason = "ORDER:%s" % order["id"]
    for line in lines_of(order["id"]):
        inv = inv_svc.find_inventory(order["store_id"], line["product_id"])
        if line["qty_picked"] > 0 and inv is not None:
            inv_svc.restock(inv, line["qty_picked"], reason)
        if line["qty_reserved"] > 0 and inv is not None:
            inv_svc.release(inv, line["qty_reserved"], reason)
        line["qty_reserved"] = 0
        line["qty_picked"] = 0
        line["line_status"] = "NOT_FULFILLED"
        touch(line)
    _slot_release(order, order["id"])
    order["refunded_total_cents"] = order["authorized_total_cents"]
    order["payment_status"] = "REFUNDED"


# --- Expiry cascade ---------------------------------------------------------

def expire_order(order):
    """AWAITING_PICKUP -> EXPIRED cascade (PRD §3.7)."""
    reason_order = "ORDER:%s" % order["id"]
    hold = hold_of(db, order["id"])
    reason_hold = "HOLD:%s" % hold["id"] if hold is not None else reason_order

    for line in lines_of(order["id"]):
        # restock picked units back to the shelf (substitute product for SUBSTITUTED)
        if line["qty_picked"] > 0:
            if line["line_status"] == "SUBSTITUTED":
                sub = _accepted_sub(line)
                prod_id = sub["substitute_product_id"] if sub else line["product_id"]
            else:
                prod_id = line["product_id"]
            inv = inv_svc.find_inventory(order["store_id"], prod_id)
            if inv is not None:
                inv_svc.restock(inv, line["qty_picked"], reason_hold)
        line["line_status"] = "NOT_FULFILLED"
        touch(line)

    for line in lines_of(order["id"]):
        if line["qty_reserved"] > 0:
            inv = inv_svc.find_inventory(order["store_id"], line["product_id"])
            if inv is not None:
                inv_svc.release(inv, line["qty_reserved"], reason_hold)
        line["qty_reserved"] = 0

    order["refunded_total_cents"] = order["authorized_total_cents"]
    order["payment_status"] = "REFUNDED"

    if hold is not None:
        hold["hold_status"] = "EXPIRED"
        touch(hold)

    _slot_release(order, order["id"])

    customer = db.customers.get(order["customer_id"])
    if customer is not None:
        customer["no_show_strikes"] += 1
        recompute_pickup_standing(customer)
        touch(customer)

    order["fulfillment_status"] = "EXPIRED"
    touch(order)


def run_expiry_sweep():
    """For every ACTIVE hold whose expires_at the clock has reached, fire expiry."""
    now = db.clock.now()
    # snapshot to avoid mutation-during-iteration
    for hold in list(db.holds.values()):
        if hold["hold_status"] != "ACTIVE":
            continue
        order = db.orders.get(hold["order_id"])
        if order is None or order["fulfillment_status"] != "AWAITING_PICKUP":
            continue
        try:
            exp = parse_iso(hold["expires_at"])
        except ValueError:
            continue
        if now >= exp:
            expire_order(order)


def _accepted_sub(line):
    for sub in db.substitutions.values():
        if sub["order_line_id"] == line["id"] and sub["decision_status"] == "ACCEPTED":
            return sub
    return None
