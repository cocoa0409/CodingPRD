"""Cascading side effects: order/shipment holds and order auto-close."""

import db


def cascade_order_hold(order):
    """CLEARED|LICENSED -> HELD with pre_hold_status recorded; the order's
    shipments in PLANNED|SCREENED cascade to HELD."""
    if order["status"] not in ("CLEARED", "LICENSED"):
        return
    order["pre_hold_status"] = order["status"]
    order["status"] = "HELD"
    db.touch(order)
    for shipment in db.SHIPMENTS.values():
        if shipment["order_id"] == order["id"] and shipment["status"] in ("PLANNED", "SCREENED"):
            shipment["status"] = "HELD"
            db.touch(shipment)


def cascade_party_hold(party):
    """Hold every CLEARED|LICENSED order of the party (and their shipments)."""
    for order in db.ORDERS.values():
        if order["party_id"] == party["id"]:
            cascade_order_hold(order)


def maybe_close_order(order):
    """RELEASED -> CLOSED when every shipment is terminal and the DELIVERED
    quantity total equals the order quantity."""
    if order["status"] != "RELEASED":
        return
    shipments = [s for s in db.SHIPMENTS.values() if s["order_id"] == order["id"]]
    if not shipments:
        return
    if not all(s["status"] in ("DELIVERED", "RETURNED", "CANCELLED") for s in shipments):
        return
    delivered = sum(s["quantity"] for s in shipments if s["status"] == "DELIVERED")
    if delivered == order["quantity"]:
        order["status"] = "CLOSED"
        db.touch(order)


def check_license_exhausted(license_):
    """APPROVED -> EXHAUSTED after a decrement when either remaining hits 0."""
    if license_["status"] == "APPROVED" and (
        license_["remaining_quantity"] == 0 or license_["remaining_value_cents"] == 0
    ):
        license_["status"] = "EXHAUSTED"


def check_license_reactivation(license_):
    """EXHAUSTED -> APPROVED when a return restores both remaining values above
    zero and the validity window has not passed."""
    if (
        license_["status"] == "EXHAUSTED"
        and license_["remaining_quantity"] > 0
        and license_["remaining_value_cents"] > 0
        and db.today() <= license_["valid_until"]
    ):
        license_["status"] = "APPROVED"
