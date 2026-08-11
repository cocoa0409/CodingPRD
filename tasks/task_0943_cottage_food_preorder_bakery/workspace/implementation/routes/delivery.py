"""Delivery routes: creation, sequencing, the resequence loop, dispatch, completion."""

from flask import Blueprint

import config
from db import DB, base_record, touch
from errors import ApiError
from ladder import endpoint
from response import created, ok
from routes.common import list_endpoint
from serialize import dump
from services.gates import require_state
from tsutil import num2, round_half_up

bp = Blueprint("delivery", __name__)

ADMIN = config.ROLE_ADMIN
BAKER = config.ROLE_BAKER


def assigned_orders(route_id):
    return [o for o in DB.values("orders")
            if o.get("delivery_route_id") == route_id]


@bp.post("/bakery/delivery-routes")
@endpoint(roles=[BAKER])
def create_route(ctx):
    fks = ctx.body_fks(required=("offer_window_id", "baker_id"))   # rungs 8, 10
    window = fks["offer_window_id"]
    baker = fks["baker_id"]
    if window is None:
        raise ApiError("ERR_VALIDATION", "offer_window_id is required.")
    if baker is None:
        raise ApiError("ERR_VALIDATION", "baker_id is required.")
    ctx.ownership(baker_id=baker["id"])                            # rung 12

    rec = base_record(ctx.now)
    rec.update({
        "baker_id": baker["id"],
        "offer_window_id": window["id"],
        "route_status": "DRAFT",
        "stop_count": 0,
        "total_distance_km": 0,
        "dispatched_at": None,
    })
    DB.coll("delivery_routes")[rec["id"]] = rec
    return created(dump("delivery_routes", rec))


@bp.post("/bakery/delivery-routes/<delivery_route_id>/status")
@endpoint(roles=[BAKER], path=("delivery_route_id",))
def route_status(ctx):
    # CARVE-OUT: rung 16 never applies -- route status work is legal only once
    # the window is locked or later.
    route = ctx.p["delivery_route_id"]
    ctx.ownership(baker_id=route.get("baker_id"))                  # rung 12
    if ctx.body.get("to_status") is None:                           # rung 13
        raise ApiError("ERR_VALIDATION", "to_status is required.")
    to_status = ctx.enum("to_status", "route_status")               # rung 14
    window = DB.get("offer_windows", route.get("offer_window_id"))
    current = route.get("route_status")

    if to_status == "SEQUENCED":                                   # rung 19
        require_state(current, ("DRAFT",), "route_status")
        if not assigned_orders(route["id"]):
            raise ApiError("ERR_INVALID_STATE",
                           "No order is assigned to this route.")
        _sequence(route, ctx.now)
    elif to_status == "DRAFT":
        require_state(current, ("SEQUENCED",), "route_status")
        for order in assigned_orders(route["id"]):
            if order.get("stop_sequence") is not None:
                order["stop_sequence"] = None
                touch(order, ctx.now)
        route["stop_count"] = 0
    elif to_status == "DISPATCHED":
        require_state(current, ("SEQUENCED",), "route_status")
        if (window or {}).get("window_status") != "HANDOFF_OPEN":
            raise ApiError("ERR_INVALID_STATE",
                           "Dispatch requires a HANDOFF_OPEN window.")
        route["dispatched_at"] = ctx.now
        for order in assigned_orders(route["id"]):
            if (order.get("handoff_status") == "SCHEDULED"
                    and order.get("order_status") == "READY"):
                order["handoff_status"] = "OUT_FOR_DELIVERY"
                touch(order, ctx.now)
    elif to_status == "COMPLETED":
        require_state(current, ("DISPATCHED",), "route_status")
        for order in assigned_orders(route["id"]):
            if order.get("handoff_status") == "OUT_FOR_DELIVERY":
                raise ApiError("ERR_INVALID_STATE",
                               "An assigned order is still OUT_FOR_DELIVERY.")
    else:  # pragma: no cover - the enum has exactly four members
        raise ApiError("ERR_INVALID_STATE", "Unreachable target.")
    route["route_status"] = to_status
    touch(route, ctx.now)
    return ok(dump("delivery_routes", route))


def _sequence(route, now):
    """calculations.route_stop_sequence -- distance ASC, created_at ASC, never id."""
    eligible = [o for o in assigned_orders(route["id"])
                if o.get("handoff_status") == "SCHEDULED"
                and o.get("order_status") in ("CONFIRMED", "IN_PRODUCTION", "READY")]
    eligible.sort(key=lambda o: (float(o.get("delivery_distance_km") or 0),
                                 o["created_at"].dt, o["id"]))
    total = 0
    for index, order in enumerate(eligible, start=1):
        order["stop_sequence"] = index
        touch(order, now)
        total += float(order.get("delivery_distance_km") or 0)
    route["stop_count"] = len(eligible)
    route["total_distance_km"] = num2(round_half_up(total, 2))


@bp.get("/bakery/delivery-routes/<delivery_route_id>")
@endpoint(roles=[BAKER, ADMIN], path=("delivery_route_id",))
def read_route(ctx):
    route = ctx.p["delivery_route_id"]
    ctx.ownership(baker_id=route.get("baker_id"))
    return ok(dump("delivery_routes", route))


@bp.get("/bakery/delivery-routes")
@endpoint(roles=[BAKER, ADMIN], list_ep=True)
def list_routes(ctx):
    return list_endpoint(ctx, "delivery_routes", {
        "baker_id": "baker_id",
        "offer_window_id": "offer_window_id",
        "route_status": "route_status",
    })
