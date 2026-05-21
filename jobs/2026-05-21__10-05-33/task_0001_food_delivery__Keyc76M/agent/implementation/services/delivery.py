"""Delivery cascade — the most complex side-effect chain in the system.

When a rider invokes /assignments/{id}/deliver, this module runs the
full fiscal reconciliation: final fee, final commission, late fine,
wallet credit, settlement update, route-group completion.
"""

import math

import compute
import state
from services import orders as osvc
from services import restaurants as rest_svc
from services import riders as rsvc
from services import fines as fines_svc


def deliver(assignment, order, rider):
    now = state.now()
    assignment["status"] = "DELIVERED"
    assignment["delivered_at"] = now

    # Order cascade
    order["status"] = "DELIVERED"
    order["actual_delivery_time"] = now
    delta = now - order["promised_delivery_time"]
    minutes_late = max(0, int(math.floor(delta.total_seconds() / 60.0)))
    order["minutes_late"] = minutes_late

    # Reconciled delivery fee (solo + possible merge discount)
    solo_fee = compute.solo_delivery_fee_cents(
        order["distance_km"], order["is_peak"]
    )
    final_fee = solo_fee
    rg = None
    if assignment.get("route_group_id"):
        rg = state.STORE.route_groups.get(assignment["route_group_id"])
        if rg is not None and len(rg["assignment_ids"]) >= 2:
            discount = compute.merge_discount_cents(solo_fee)
            final_fee = solo_fee - discount

    order["final_delivery_fee_cents"] = final_fee
    assignment["final_delivery_fee_cents"] = final_fee

    # Reconciled commission
    restaurant = state.STORE.restaurants[order["restaurant_id"]]
    final_commission = compute.commission_cents(
        order["subtotal_cents"], restaurant["commission_rate_override"]
    )
    order["final_commission_cents"] = final_commission

    # Payment capture & credit draw-down
    customer = state.STORE.customers.get(order["customer_id"])
    customer_total = order["subtotal_cents"] + final_fee
    if customer is not None:
        applied = min(customer["credit_balance_cents"], customer_total)
        customer["credit_balance_cents"] -= applied
        from services import customers as csvc
        csvc.bump(customer)
    order["payment_status"] = "CAPTURED"
    osvc.bump(order)

    # Restaurant settlement
    restaurant["pending_settlement_cents"] += (
        order["subtotal_cents"] - final_commission
    )
    rest_svc.bump(restaurant)

    # Rider wallet + delivery history
    rider["wallet_balance_cents"] += final_fee
    rsvc.record_delivery_outcome(rider["id"], on_time=(minutes_late == 0))
    rsvc.recompute_on_time_rate(rider)
    rsvc.recompute_bonus_tier(rider)
    rsvc.bump(rider)

    # Late fine cascade
    if minutes_late > 0:
        amount = compute.late_fine_amount_cents(minutes_late, final_fee)
        fines_svc.issue_rider_fine(
            rider, "LATE_DELIVERY", amount,
            related_order_id=order["id"],
        )

    # RouteGroup completion check
    if rg is not None:
        all_delivered = all(
            state.STORE.assignments[aid]["status"] == "DELIVERED"
            for aid in rg["assignment_ids"]
            if aid in state.STORE.assignments
        )
        if all_delivered:
            rg["status"] = "COMPLETED"

    # Rider state: return to AVAILABLE if no live assignments remain.
    if not rsvc.rider_has_blocking_assignments(rider["id"]):
        rider["status"] = "AVAILABLE"
        rsvc.bump(rider)

    return assignment
