"""Delivery (courier) lifecycle and settlement (PRD §3.8, §3.9)."""
import errors
from common import touch
from db import store
from serializers import dasher_active_delivery_count
from services import calculations as calc


def _earnings_for_delivery(delivery_id):
    for e in store.earnings_records.values():
        if e["delivery_id"] == delivery_id:
            return e
    return None


def accept_delivery(delivery, dasher):
    if delivery["fulfillment_status"] != "OFFERED":
        raise errors.err(errors.ERR_INVALID_DELIVERY_STATE)
    # Counting this delivery, active_delivery_count must not exceed max_batch_size.
    # This delivery is already OFFERED, so it is included in the live count.
    if dasher_active_delivery_count(dasher["id"]) > dasher["max_batch_size"]:
        raise errors.err(errors.ERR_BATCH_LIMIT_EXCEEDED)
    delivery["fulfillment_status"] = "ACCEPTED"
    touch(delivery)


def decline_delivery(delivery, order):
    if delivery["fulfillment_status"] != "OFFERED":
        raise errors.err(errors.ERR_INVALID_DELIVERY_STATE)
    delivery["fulfillment_status"] = "REASSIGNED"
    touch(delivery)
    earnings = _earnings_for_delivery(delivery["id"])
    if earnings is not None and earnings["status"] == "ACCRUED":
        earnings["status"] = "REVERSED"
        touch(earnings)
    # Revert parent order ROUTED -> PLACED so it can be re-dispatched.
    order["fulfillment_status"] = "PLACED"
    touch(order)


def pickup_delivery(delivery, order):
    if order["fulfillment_status"] != "ROUTED":
        raise errors.err(errors.ERR_INVALID_ORDER_STATE)
    if delivery["fulfillment_status"] != "ACCEPTED":
        raise errors.err(errors.ERR_INVALID_DELIVERY_STATE)
    delivery["fulfillment_status"] = "EN_ROUTE"
    touch(delivery)
    order["fulfillment_status"] = "PICKED_UP"
    touch(order)


def deliver_delivery(delivery, order):
    if order["fulfillment_status"] != "PICKED_UP":
        raise errors.err(errors.ERR_INVALID_ORDER_STATE)
    if delivery["fulfillment_status"] != "EN_ROUTE":
        raise errors.err(errors.ERR_INVALID_DELIVERY_STATE)
    # Cross-axis billing settlement requires billing to be UNSETTLED now.
    if order["billing_status"] != "UNSETTLED":
        raise errors.err(errors.ERR_INVALID_BILLING_STATE)

    zone = store.zones[order["zone_id"]]

    # Settled delivery fee (demand EXCLUDES this order). Computed while the order
    # is still PICKED_UP (counted in active demand), so the calc subtracts 1.
    order["delivery_fee_final_cents"] = calc.delivery_fee_final(order, zone, delivery)

    # Settled dasher pay (current tip, guarantee re-evaluated).
    components = calc.dasher_pay_components(zone, delivery["route_distance_km"], order["tip_cents"])
    delivery["settled_pay_cents"] = components["total_cents"]

    # Transition states.
    delivery["fulfillment_status"] = "DELIVERED"
    touch(delivery)
    order["fulfillment_status"] = "DELIVERED"
    order["billing_status"] = "SETTLED"
    touch(order)

    # Settle earnings record (ACCRUED -> SETTLED) with the split.
    earnings = _earnings_for_delivery(delivery["id"])
    if earnings is not None:
        if earnings["status"] != "ACCRUED":
            raise errors.err(errors.ERR_EARNINGS_NOT_ACCRUED)
        earnings["base_component_cents"] = components["base_component_cents"]
        earnings["tip_component_cents"] = components["tip_component_cents"]
        earnings["guarantee_topup_cents"] = components["guarantee_topup_cents"]
        earnings["settled_pay_cents"] = components["total_cents"]
        earnings["status"] = "SETTLED"
        touch(earnings)
    # Dasher.lifetime_earnings_cents and Zone.active_order_count are re-derived
    # on read (the order leaving PICKED_UP removes it from the active pool).
