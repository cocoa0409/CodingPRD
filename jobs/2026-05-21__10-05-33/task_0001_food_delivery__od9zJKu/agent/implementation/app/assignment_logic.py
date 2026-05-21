"""Assignment lifecycle: accept, reject, pickup, deliver, cancel; route merge."""
from __future__ import annotations

from . import dispatch, metrics
from .clock import iso_now
from .entities import bump, init_unversioned
from .envelope import (
    err_forbidden,
    err_invalid_state,
    err_order_already_assigned,
)
from .geo import haversine_km
from .pricing import (
    commission_flat_cents,
    commission_tiered_cents,
    delivery_fee_solo_cents,
    late_fine_cents,
    merge_discount_cents,
)
from .store import store


def _record_offer_outcome(rider: dict, outcome: str) -> None:
    """Push outcome ("ACCEPTED" or "REJECTED") and recompute acceptance_rate / tier."""
    rider.setdefault("_offer_history", []).append(outcome)
    metrics.recompute_all(rider)


def _existing_active_assignment_for_order(order_id: str, exclude_id: str | None = None) -> dict | None:
    """Find another non-terminal assignment for this order. ACCEPTED/PICKED_UP only —
    OFFERED is allowed to coexist (multiple offers are possible), but only one acceptance
    can stick (first-writer-wins). The losing accept call will see ACCEPTED/PICKED_UP and fail."""
    for a in store.assignments.values():
        if a["order_id"] != order_id:
            continue
        if exclude_id and a["id"] == exclude_id:
            continue
        if a["status"] in ("ACCEPTED", "PICKED_UP"):
            return a
    return None


def _attach_to_route_group(rider: dict, new_assignment: dict) -> None:
    """If rider has an ACTIVE RouteGroup with an unpicked assignment whose pickup
    restaurant is within 500m of the new order's pickup restaurant, attach to it."""
    new_order = store.orders[new_assignment["order_id"]]
    target_rest = store.restaurants[new_order["restaurant_id"]]
    for grp in store.route_groups.values():
        if grp["rider_id"] != rider["id"] or grp["status"] != "ACTIVE":
            continue
        merged = False
        for aid in grp["assignment_ids"]:
            existing = store.assignments.get(aid)
            if not existing or existing["status"] not in ("OFFERED", "ACCEPTED"):
                continue
            existing_order = store.orders.get(existing["order_id"])
            if not existing_order:
                continue
            existing_rest = store.restaurants[existing_order["restaurant_id"]]
            d_km = haversine_km(
                target_rest["lat"], target_rest["lng"], existing_rest["lat"], existing_rest["lng"]
            )
            if d_km <= 0.5:
                merged = True
                break
        if merged:
            grp["assignment_ids"].append(new_assignment["id"])
            new_assignment["route_group_id"] = grp["id"]
            return


def _ensure_route_group_if_needed(rider: dict, new_assignment: dict) -> None:
    """If rider already has another active assignment that this one could be paired with
    (or had a pre-existing solo), promote/create a RouteGroup. Per PRD: route merging
    is triggered when accepting a NEW order while the rider already has an ACTIVE RouteGroup
    with a pickup restaurant within 500m. So we only merge into an existing group.

    However, a RouteGroup needs to exist for there to be merging. The PRD implies route
    groups arise only via the merge act itself. Specifically: "When the accepting rider
    already holds an ACTIVE RouteGroup ..." — so the first accepted assignment is solo
    (no group), and a second nearby one creates a group? Re-reading: "the new assignment
    is attached to that RouteGroup — its route_group_id is set to the group's id".

    Interpretation: a RouteGroup is created on acceptance of the SECOND order (the merge
    trigger). Both that order and the rider's pre-existing solo order are pulled into
    a new RouteGroup at that moment.
    """
    # Check whether rider has another live assignment NOT in a group yet
    others = []
    for a in store.assignments.values():
        if a["id"] == new_assignment["id"]:
            continue
        if a["rider_id"] != rider["id"]:
            continue
        if a["status"] in ("ACCEPTED", "PICKED_UP"):
            others.append(a)
    if not others:
        return
    # Check distance vs the new order's pickup
    new_order = store.orders[new_assignment["order_id"]]
    target_rest = store.restaurants[new_order["restaurant_id"]]
    for other in others:
        other_order = store.orders.get(other["order_id"])
        if not other_order:
            continue
        other_rest = store.restaurants[other_order["restaurant_id"]]
        if haversine_km(target_rest["lat"], target_rest["lng"], other_rest["lat"], other_rest["lng"]) <= 0.5:
            grp_id = other.get("route_group_id")
            if grp_id and grp_id in store.route_groups and store.route_groups[grp_id]["status"] == "ACTIVE":
                grp = store.route_groups[grp_id]
            else:
                # Create a new RouteGroup pulling both in
                grp = init_unversioned("RouteGroup")
                grp.update(
                    {
                        "rider_id": rider["id"],
                        "assignment_ids": [],
                        "merged_at": iso_now(),
                        "status": "ACTIVE",
                    }
                )
                store.route_groups[grp["id"]] = grp
                if other["id"] not in grp["assignment_ids"]:
                    grp["assignment_ids"].append(other["id"])
                    other["route_group_id"] = grp["id"]
            if new_assignment["id"] not in grp["assignment_ids"]:
                grp["assignment_ids"].append(new_assignment["id"])
                new_assignment["route_group_id"] = grp["id"]
            return


def accept_assignment(rider: dict, assignment: dict) -> None:
    """Rider accepts an OFFERED assignment. Cascades rider status, attaches to route group."""
    if assignment["rider_id"] != rider["id"]:
        raise err_forbidden("Rider identity mismatch")
    if assignment["status"] != "OFFERED":
        raise err_invalid_state(f"Cannot accept assignment in state {assignment['status']}")
    if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
        raise err_invalid_state(f"Rider must be AVAILABLE or ON_DELIVERY (currently {rider['status']})")
    order = store.orders.get(assignment["order_id"])
    if not order:
        raise err_invalid_state("Order missing")
    if order["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise err_invalid_state(f"Order must be in accept-eligible state (currently {order['status']})")
    # Uniqueness on order: no other ACTIVE assignment for the same order
    if _existing_active_assignment_for_order(order["id"], exclude_id=assignment["id"]):
        raise err_order_already_assigned()
    assignment["status"] = "ACCEPTED"
    assignment["accepted_at"] = iso_now()
    # Cascade rider AVAILABLE -> ON_DELIVERY
    if rider["status"] == "AVAILABLE":
        rider["status"] = "ON_DELIVERY"
    # Record offer outcome and recompute metrics
    _record_offer_outcome(rider, "ACCEPTED")
    bump(rider)
    # Route merge (if eligible)
    _ensure_route_group_if_needed(rider, assignment)


def reject_assignment(rider: dict, assignment: dict, *, redispatch: bool = True) -> dict | None:
    """Rider rejects an OFFERED assignment; recomputes acceptance, optionally redispatches."""
    if assignment["rider_id"] != rider["id"]:
        raise err_forbidden("Rider identity mismatch")
    if assignment["status"] != "OFFERED":
        raise err_invalid_state(f"Cannot reject assignment in state {assignment['status']}")
    assignment["status"] = "REJECTED"
    _record_offer_outcome(rider, "REJECTED")
    bump(rider)
    if redispatch:
        order = store.orders.get(assignment["order_id"])
        if order:
            try:
                return dispatch.open_dispatch(order)
            except Exception:
                return None
    return None


def timeout_sweep_assignment(assignment: dict) -> dict | None:
    """Sweep an OFFERED assignment that has timed out (60s) to REJECTED + redispatch."""
    if assignment["status"] != "OFFERED":
        return None
    rider = store.riders.get(assignment["rider_id"])
    if not rider:
        return None
    assignment["status"] = "REJECTED"
    _record_offer_outcome(rider, "REJECTED")
    bump(rider)
    order = store.orders.get(assignment["order_id"])
    if order:
        try:
            return dispatch.open_dispatch(order)
        except Exception:
            return None
    return None


def pickup_assignment(rider: dict, assignment: dict) -> None:
    if assignment["rider_id"] != rider["id"]:
        raise err_forbidden("Rider identity mismatch")
    if assignment["status"] != "ACCEPTED":
        raise err_invalid_state(f"Cannot pick up assignment in state {assignment['status']}")
    order = store.orders.get(assignment["order_id"])
    if not order or order["status"] != "READY_FOR_PICKUP":
        raise err_invalid_state("Order is not READY_FOR_PICKUP")
    assignment["status"] = "PICKED_UP"
    assignment["picked_up_at"] = iso_now()
    order["status"] = "PICKED_UP"
    bump(order)


def cancel_assignment_by_rider(rider: dict, assignment: dict) -> dict | None:
    """Rider cancels after acceptance; creates RIDER_NO_SHOW fine; debits wallet; redispatches."""
    if assignment["rider_id"] != rider["id"]:
        raise err_forbidden("Rider identity mismatch")
    if assignment["status"] != "ACCEPTED":
        raise err_invalid_state(
            f"Cancel only valid in ACCEPTED state (currently {assignment['status']})"
        )
    order = store.orders.get(assignment["order_id"])
    if order and order["status"] == "PICKED_UP":
        raise err_invalid_state("Cannot cancel after pickup")
    assignment["status"] = "CANCELLED"
    # Create fine
    fine = init_unversioned("Fine")
    fine.update(
        {
            "subject_type": "RIDER",
            "subject_id": rider["id"],
            "reason": "RIDER_NO_SHOW",
            "amount_cents": 500,
            "settlement_status": "PENDING",
        }
    )
    store.fines[fine["id"]] = fine
    rider["wallet_balance_cents"] = rider.get("wallet_balance_cents", 0) - 500
    metrics.recompute_all(rider)
    bump(rider)
    # Remove from route group's active set; group stays ACTIVE unless empty
    grp_id = assignment.get("route_group_id")
    if grp_id and grp_id in store.route_groups:
        # No-op: assignment is now CANCELLED; the group reflects history.
        pass
    # If no other active assignment remains for the rider, drop to AVAILABLE
    _maybe_set_rider_available(rider)
    # Redispatch
    if order:
        try:
            return dispatch.open_dispatch(order)
        except Exception:
            return None
    return None


def _maybe_set_rider_available(rider: dict) -> None:
    if rider["status"] != "ON_DELIVERY":
        return
    for a in store.assignments.values():
        if a["rider_id"] == rider["id"] and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            return
    rider["status"] = "AVAILABLE"


def deliver_assignment(rider: dict, assignment: dict) -> dict:
    """Complete delivery cascade with fiscal reconciliation."""
    from .clock import clock as _clock
    import datetime as _dt

    if assignment["rider_id"] != rider["id"]:
        raise err_forbidden("Rider identity mismatch")
    if assignment["status"] != "PICKED_UP":
        raise err_invalid_state(f"Cannot deliver assignment in state {assignment['status']}")
    order = store.orders.get(assignment["order_id"])
    if not order or order["status"] != "PICKED_UP":
        raise err_invalid_state("Order is not PICKED_UP")

    now = _clock.now()
    promised = _dt.datetime.fromisoformat(order["promised_delivery_time"].replace("Z", "+00:00"))
    delta_seconds = (now - promised).total_seconds()
    minutes_late = max(0, int(delta_seconds // 60))

    assignment["status"] = "DELIVERED"
    assignment["delivered_at"] = _iso(now)
    order["status"] = "DELIVERED"
    order["actual_delivery_time"] = _iso(now)
    order["minutes_late"] = minutes_late

    # Final delivery fee (with merge discount if applicable)
    solo_fee = delivery_fee_solo_cents(order["distance_km"], order["is_peak"])
    grp_id = assignment.get("route_group_id")
    final_fee = solo_fee
    if grp_id and grp_id in store.route_groups:
        grp = store.route_groups[grp_id]
        if len(grp["assignment_ids"]) >= 2:
            final_fee = solo_fee - merge_discount_cents(solo_fee)
    order["final_delivery_fee_cents"] = final_fee
    assignment["final_delivery_fee_cents"] = final_fee

    # Final commission
    restaurant = store.restaurants[order["restaurant_id"]]
    rate = restaurant.get("commission_rate_override")
    if rate is not None:
        order["final_commission_cents"] = commission_flat_cents(order["subtotal_cents"], float(rate))
    else:
        order["final_commission_cents"] = commission_tiered_cents(order["subtotal_cents"])

    # payment_status -> CAPTURED
    order["payment_status"] = "CAPTURED"

    # Late fine
    if minutes_late > 0:
        fine = init_unversioned("Fine")
        fine.update(
            {
                "subject_type": "RIDER",
                "subject_id": rider["id"],
                "reason": "LATE_DELIVERY",
                "amount_cents": late_fine_cents(minutes_late, final_fee),
                "settlement_status": "PENDING",
            }
        )
        store.fines[fine["id"]] = fine
        rider["wallet_balance_cents"] = rider.get("wallet_balance_cents", 0) - fine["amount_cents"]

    # Restaurant pending_settlement_cents += subtotal - final_commission
    restaurant["pending_settlement_cents"] = (
        restaurant.get("pending_settlement_cents", 0)
        + order["subtotal_cents"]
        - order["final_commission_cents"]
    )
    bump(restaurant)

    # Rider wallet credit (delivery fee, net of merge discount absorbed by platform)
    rider["wallet_balance_cents"] = rider.get("wallet_balance_cents", 0) + final_fee
    # Delivery counts as on-time iff minutes_late == 0
    rider.setdefault("_delivery_history", []).append(minutes_late == 0)
    metrics.recompute_all(rider)
    bump(rider)
    bump(order)

    # RouteGroup completion check
    if grp_id and grp_id in store.route_groups:
        grp = store.route_groups[grp_id]
        all_delivered = all(
            store.assignments[aid]["status"] == "DELIVERED" for aid in grp["assignment_ids"]
        )
        if all_delivered:
            grp["status"] = "COMPLETED"

    # Rider returns to AVAILABLE iff no other active assignments
    _maybe_set_rider_available(rider)

    return assignment


def _iso(dt) -> str:
    """Format datetime as ISO 8601 Z with 3-digit ms."""
    if dt.tzinfo is None:
        import datetime as _dt
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    else:
        import datetime as _dt
        dt = dt.astimezone(_dt.timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = int(dt.microsecond / 1000)
    return f"{s}.{ms:03d}Z"
