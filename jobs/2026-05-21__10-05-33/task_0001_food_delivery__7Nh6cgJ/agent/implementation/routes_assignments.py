"""Assignment endpoints + delivery reconciliation."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from auth import require_role
from clock import CLOCK
from envelope import success
from errors import APIError
from fines_logic import create_rider_fine
from geo import haversine_km
from ids import new_id
from pricing import (flat_commission_cents, merged_delivery_fee_cents,
                     solo_delivery_fee_cents, tiered_commission_cents)
from resources import touch
from rider_metrics import recompute_acceptance_rate, recompute_bonus_tier, recompute_on_time_rate
from store import STORE


def serialize_assignment(a: dict) -> dict:
    return {
        "id": a["id"],
        "order_id": a["order_id"],
        "rider_id": a["rider_id"],
        "status": a["status"],
        "offered_at": a.get("offered_at"),
        "accepted_at": a.get("accepted_at"),
        "picked_up_at": a.get("picked_up_at"),
        "delivered_at": a.get("delivered_at"),
        "final_delivery_fee_cents": a.get("final_delivery_fee_cents"),
        "route_group_id": a.get("route_group_id"),
        "created_at": a["created_at"],
    }


def _parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _live_assignment_for_order(order_id: str) -> dict | None:
    for a in STORE.assignments.values():
        if a["order_id"] == order_id and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            return a
    return None


def _active_route_group_for(rider_id: str) -> dict | None:
    for g in STORE.route_groups.values():
        if g["rider_id"] == rider_id and g["status"] == "ACTIVE":
            return g
    return None


def _other_active_assignments(rider_id: str, exclude: str) -> list[dict]:
    return [a for a in STORE.assignments.values()
            if a["rider_id"] == rider_id and a["id"] != exclude
            and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")]


def register(app):
    @app.get("/api/assignments/<aid>")
    def read_assignment(aid: str):
        user_id, role = require_role({"PlatformAdmin", "Rider", "CustomerService"})
        with STORE.lock:
            a = STORE.assignments.get(aid)
            if a is None:
                raise APIError("ERR_NOT_FOUND", "No such assignment.")
            if role == "Rider" and user_id != a["rider_id"]:
                raise APIError("ERR_FORBIDDEN")
            return success(serialize_assignment(a))

    @app.post("/api/assignments/<aid>/accept")
    def accept_assignment(aid: str):
        user_id, _ = require_role({"Rider"})
        with STORE.lock:
            a = STORE.assignments.get(aid)
            if a is None:
                raise APIError("ERR_NOT_FOUND", "No such assignment.")
            if user_id != a["rider_id"]:
                raise APIError("ERR_FORBIDDEN")
            if a["status"] != "OFFERED":
                raise APIError("ERR_INVALID_STATE", "Assignment is not in OFFERED.")
            order = STORE.orders.get(a["order_id"])
            if order is None or order["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
                raise APIError("ERR_INVALID_STATE", "Order is not in an acceptable state.")
            rider = STORE.riders[a["rider_id"]]
            if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
                raise APIError("ERR_INVALID_STATE", "Rider not in AVAILABLE or ON_DELIVERY.")

            # Uniqueness: no other Assignment for this order is already past OFFERED
            # (i.e., already ACCEPTED or PICKED_UP). First-writer-wins per PRD §3.6:
            # multiple concurrently-OFFERED assignments may exist; whichever rider's
            # /accept lands first wins, and subsequent attempts see an ACCEPTED peer
            # and fail with ERR_ORDER_ALREADY_ASSIGNED.
            for other in STORE.assignments.values():
                if other["id"] == a["id"]:
                    continue
                if other["order_id"] == a["order_id"] and other["status"] in ("ACCEPTED", "PICKED_UP"):
                    raise APIError("ERR_ORDER_ALREADY_ASSIGNED")

            a["status"] = "ACCEPTED"
            a["accepted_at"] = CLOCK.now_iso()
            # Rider state cascade
            if rider["status"] == "AVAILABLE":
                rider["status"] = "ON_DELIVERY"
            recompute_acceptance_rate(rider)
            recompute_bonus_tier(rider)
            touch(rider)

            # Route merging
            restaurant = STORE.restaurants[order["restaurant_id"]]
            close_peers = []
            for peer in STORE.assignments.values():
                if peer["id"] == a["id"]:
                    continue
                if peer["rider_id"] != rider["id"]:
                    continue
                if peer["status"] not in ("ACCEPTED",):
                    # only unpicked, already-accepted peers qualify
                    continue
                peer_order = STORE.orders.get(peer["order_id"])
                if peer_order is None:
                    continue
                peer_rest = STORE.restaurants.get(peer_order["restaurant_id"])
                if peer_rest is None:
                    continue
                d_m = haversine_km(restaurant["lat"], restaurant["lng"],
                                    peer_rest["lat"], peer_rest["lng"]) * 1000.0
                if d_m <= 500.0:
                    close_peers.append(peer)
            if close_peers:
                # Prefer extending an existing ACTIVE group whose peer is in close_peers.
                target_group = None
                for peer in close_peers:
                    if peer.get("route_group_id"):
                        target_group = STORE.route_groups.get(peer["route_group_id"])
                        if target_group is not None and target_group["status"] == "ACTIVE":
                            break
                        target_group = None
                if target_group is not None:
                    a["route_group_id"] = target_group["id"]
                    target_group["assignment_ids"].append(a["id"])
                else:
                    group_id = new_id()
                    group = {
                        "id": group_id,
                        "rider_id": rider["id"],
                        "assignment_ids": [p["id"] for p in close_peers] + [a["id"]],
                        "merged_at": CLOCK.now_iso(),
                        "status": "ACTIVE",
                        "created_at": CLOCK.now_iso(),
                    }
                    STORE.route_groups[group_id] = group
                    for p in close_peers:
                        p["route_group_id"] = group_id
                    a["route_group_id"] = group_id

            return success(serialize_assignment(a))

    @app.post("/api/assignments/<aid>/reject")
    def reject_assignment(aid: str):
        user_id, _ = require_role({"Rider"})
        with STORE.lock:
            a = STORE.assignments.get(aid)
            if a is None:
                raise APIError("ERR_NOT_FOUND", "No such assignment.")
            if user_id != a["rider_id"]:
                raise APIError("ERR_FORBIDDEN")
            if a["status"] != "OFFERED":
                raise APIError("ERR_INVALID_STATE", "Assignment is not in OFFERED.")
            a["status"] = "REJECTED"
            rider = STORE.riders[a["rider_id"]]
            recompute_acceptance_rate(rider)
            recompute_bonus_tier(rider)
            touch(rider)
            order = STORE.orders.get(a["order_id"])
            if order is not None and order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
                from dispatch_engine import open_dispatch
                if _live_assignment_for_order(order["id"]) is None:
                    open_dispatch(order)
            return success(serialize_assignment(a))

    @app.post("/api/assignments/<aid>/pickup")
    def pickup_assignment(aid: str):
        user_id, _ = require_role({"Rider"})
        with STORE.lock:
            a = STORE.assignments.get(aid)
            if a is None:
                raise APIError("ERR_NOT_FOUND", "No such assignment.")
            if user_id != a["rider_id"]:
                raise APIError("ERR_FORBIDDEN")
            if a["status"] != "ACCEPTED":
                raise APIError("ERR_INVALID_STATE", "Assignment is not in ACCEPTED.")
            order = STORE.orders.get(a["order_id"])
            if order is None or order["status"] != "READY_FOR_PICKUP":
                raise APIError("ERR_INVALID_STATE", "Order is not READY_FOR_PICKUP.")
            a["status"] = "PICKED_UP"
            a["picked_up_at"] = CLOCK.now_iso()
            order["status"] = "PICKED_UP"
            touch(order)
            return success(serialize_assignment(a))

    @app.post("/api/assignments/<aid>/deliver")
    def deliver_assignment(aid: str):
        user_id, _ = require_role({"Rider"})
        with STORE.lock:
            a = STORE.assignments.get(aid)
            if a is None:
                raise APIError("ERR_NOT_FOUND", "No such assignment.")
            if user_id != a["rider_id"]:
                raise APIError("ERR_FORBIDDEN")
            if a["status"] != "PICKED_UP":
                raise APIError("ERR_INVALID_STATE", "Assignment is not PICKED_UP.")
            order = STORE.orders.get(a["order_id"])
            if order is None or order["status"] != "PICKED_UP":
                raise APIError("ERR_INVALID_STATE", "Order is not PICKED_UP.")

            now = CLOCK.now()
            a["status"] = "DELIVERED"
            a["delivered_at"] = CLOCK.now_iso()
            order["actual_delivery_time"] = a["delivered_at"]
            promised_dt = _parse_iso(order["promised_delivery_time"])
            seconds_late = (now - promised_dt).total_seconds()
            minutes_late = int(math.floor(max(0.0, seconds_late) / 60.0))
            order["minutes_late"] = minutes_late

            # final_delivery_fee_cents reconciliation
            solo = solo_delivery_fee_cents(order["distance_km"], order["is_peak"])
            final_fee = solo
            if a.get("route_group_id"):
                group = STORE.route_groups.get(a["route_group_id"])
                if group is not None and len(group["assignment_ids"]) >= 2:
                    final_fee = merged_delivery_fee_cents(solo)
            order["final_delivery_fee_cents"] = final_fee
            a["final_delivery_fee_cents"] = final_fee

            # final_commission_cents reconciliation
            restaurant = STORE.restaurants[order["restaurant_id"]]
            override = restaurant.get("commission_rate_override")
            if override is None:
                final_commission = tiered_commission_cents(order["subtotal_cents"])
            else:
                final_commission = flat_commission_cents(order["subtotal_cents"], override)
            order["final_commission_cents"] = final_commission

            # payment status
            order["payment_status"] = "CAPTURED"

            # Restaurant settlement: subtotal - final_commission
            restaurant["pending_settlement_cents"] = (
                int(restaurant["pending_settlement_cents"]) + int(order["subtotal_cents"]) - int(final_commission)
            )
            touch(restaurant)

            # Rider wallet credit
            rider = STORE.riders[a["rider_id"]]
            rider["wallet_balance_cents"] = int(rider["wallet_balance_cents"]) + int(final_fee)

            # Order: status DELIVERED, mutation
            order["status"] = "DELIVERED"
            touch(order)

            # Recompute rider metrics
            recompute_on_time_rate(rider)
            recompute_acceptance_rate(rider)
            recompute_bonus_tier(rider)

            # Late delivery fine
            if minutes_late > 0:
                fine_amount = _late_fine_amount(minutes_late, final_fee)
                create_rider_fine(rider["id"], "LATE_DELIVERY", fine_amount)
                # create_rider_fine recomputes bonus_tier and touches rider.

            touch(rider)

            # RouteGroup completion + rider state cascade
            still_active = _other_active_assignments(rider["id"], exclude=a["id"])
            if a.get("route_group_id"):
                group = STORE.route_groups[a["route_group_id"]]
                all_done = True
                for peer_id in group["assignment_ids"]:
                    peer = STORE.assignments.get(peer_id)
                    if peer is None:
                        continue
                    if peer["status"] not in ("DELIVERED", "CANCELLED", "REJECTED"):
                        all_done = False
                        break
                if all_done:
                    group["status"] = "COMPLETED"
            if not still_active and rider["status"] == "ON_DELIVERY":
                rider["status"] = "AVAILABLE"

            return success(serialize_assignment(a))

    @app.post("/api/assignments/<aid>/cancel")
    def cancel_assignment(aid: str):
        user_id, _ = require_role({"Rider"})
        with STORE.lock:
            a = STORE.assignments.get(aid)
            if a is None:
                raise APIError("ERR_NOT_FOUND", "No such assignment.")
            if user_id != a["rider_id"]:
                raise APIError("ERR_FORBIDDEN")
            if a["status"] != "ACCEPTED":
                raise APIError("ERR_INVALID_STATE", "Only ACCEPTED assignments can be cancelled by the rider.")
            order = STORE.orders.get(a["order_id"])
            if order is not None and order["status"] == "PICKED_UP":
                raise APIError("ERR_INVALID_STATE", "Order already picked up.")
            a["status"] = "CANCELLED"

            # Rider NO_SHOW fine: 500 cents.
            rider = STORE.riders[a["rider_id"]]
            create_rider_fine(rider["id"], "RIDER_NO_SHOW", 500)
            # Rider state: if no other live assignments, set rider back to AVAILABLE.
            still_active = _other_active_assignments(rider["id"], exclude=a["id"])
            if not still_active and rider["status"] == "ON_DELIVERY":
                rider["status"] = "AVAILABLE"
                touch(rider)

            # Fresh dispatch for the order.
            if order is not None and order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
                from dispatch_engine import open_dispatch
                if _live_assignment_for_order(order["id"]) is None:
                    open_dispatch(order)
            return success(serialize_assignment(a))


def _late_fine_amount(minutes_late: int, final_delivery_fee_cents: int) -> int:
    if 1 <= minutes_late <= 10:
        return 200
    if 11 <= minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    # > 30
    clawback = min(int(final_delivery_fee_cents), 1500)
    return clawback + 500
