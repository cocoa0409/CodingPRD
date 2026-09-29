"""Cascade propagation (PRD 2.6) shared by several endpoints."""

import db
from db import store, touch
from services import calc


def refresh_asset(asset, score=False):
    """Recompute the asset's aggregates and bump its audit fields once."""
    if asset is None:
        return
    calc.recompute_committed_quantity(asset)
    if score:
        calc.recompute_compliance_score(asset)
    touch(asset)


def nomination_awaiting_schedule(nomination):
    """SCHEDULED -> AWAITING_SCHEDULE once no active order remains."""
    if nomination is None:
        return
    if nomination["fulfillment_status"] != "SCHEDULED":
        return
    for order in calc.orders_of_nomination(nomination["id"]):
        if order["logistics_status"] in calc.ACTIVE_ORDER_STATES:
            return
    nomination["fulfillment_status"] = "AWAITING_SCHEDULE"
    touch(nomination)


def cancel_order(order, cascade_nomination=True):
    """Move an order to CANCELLED with its compensations."""
    was_cleared = order["logistics_status"] == "CLEARED"
    order["logistics_status"] = "CANCELLED"
    if was_cleared:
        order["port_clearance_ref"] = None
        order["cleared_at"] = None
    touch(order)
    refresh_asset(store.delivery_assets.get(order["asset_id"]))
    if cascade_nomination:
        nomination_awaiting_schedule(calc.order_nomination(order))


def quarantine_asset(asset, triggering_order_id):
    """MAJOR spill cascade: quarantine and unwind the asset's other slots."""
    if asset["status"] == "AVAILABLE":
        asset["status"] = "QUARANTINED"
    others = [
        o
        for o in db.sorted_rows(store.delivery_orders)
        if o["asset_id"] == asset["id"]
        and o["id"] != triggering_order_id
        and o["logistics_status"] in ("SCHEDULED", "CLEARED")
    ]
    for other in others:
        cancel_order(other)
    touch(asset)


def recompute_customer_exposure(customer, strict=False):
    if customer is None:
        return
    calc.recompute_exposure(customer, strict=strict)
    touch(customer)
