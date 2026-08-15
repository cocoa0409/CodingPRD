"""DeliveryRoute and DeliveryStop endpoints (PRD 3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_EMPTY_ROUTE,
    ERR_INVALID_STATE,
    ERR_ROUTE_NOT_DISPATCHED,
    ERR_ROUTE_NOT_FOUND,
    ERR_STANDING_ORDER_NOT_FOUND,
    ERR_STOP_NOT_FOUND,
)
from middleware import get_body, req_int, req_str, require_roles
from response import success, serialize
from services import new_resource, touch
from routes.listing import list_response

bp = Blueprint("delivery", __name__)

RW = ("Grower", "OpsManager")


def _get_route(rid):
    rec = db.delivery_routes.get(rid)
    if rec is None:
        raise ApiError(404, ERR_ROUTE_NOT_FOUND, "delivery route id does not exist.")
    return rec


def _get_stop(sid):
    rec = db.delivery_stops.get(sid)
    if rec is None:
        raise ApiError(404, ERR_STOP_NOT_FOUND, "delivery stop id does not exist.")
    return rec


@bp.post("/delivery-routes")
@require_roles("OpsManager")
def create_route():
    body = get_body()
    route_code = req_str(body, "route_code")
    service_date = req_str(body, "service_date")
    min_stop_subtotal_cents = req_int(body, "min_stop_subtotal_cents")
    if min_stop_subtotal_cents < 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "min_stop_subtotal_cents must be >= 0.")
    rec = new_resource(
        {
            "route_code": route_code,
            "service_date": service_date,
            "min_stop_subtotal_cents": min_stop_subtotal_cents,
            "status": "PLANNED",
        }
    )
    db.delivery_routes[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/delivery-routes")
@require_roles(*RW)
def list_routes():
    status = request.args.get("status")
    records = list(db.delivery_routes.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@bp.get("/delivery-routes/<rid>")
@require_roles(*RW)
def get_route(rid):
    return success(serialize(_get_route(rid)), "object", 200)


@bp.post("/delivery-routes/<rid>/stops")
@require_roles("OpsManager")
def add_stop(rid):
    route = _get_route(rid)
    body = get_body()
    customer_id = req_str(body, "customer_id")
    standing_order_id = req_str(body, "standing_order_id")
    if customer_id not in db.customers:
        raise ApiError(404, ERR_CUSTOMER_NOT_FOUND, "customer_id does not exist.")
    if standing_order_id not in db.standing_orders:
        raise ApiError(
            404, ERR_STANDING_ORDER_NOT_FOUND, "standing order id does not exist."
        )
    if route["status"] != "PLANNED":
        raise ApiError(
            409, ERR_INVALID_STATE, "Stops can only be added to a PLANNED route."
        )
    rec = new_resource(
        {
            "route_id": route["id"],
            "customer_id": customer_id,
            "standing_order_id": standing_order_id,
            "stop_subtotal_cents": 0,
            "outcome": "SCHEDULED",
        }
    )
    db.delivery_stops[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/delivery-routes/<rid>/stops")
@require_roles(*RW)
def list_route_stops(rid):
    _get_route(rid)
    records = [s for s in db.delivery_stops.values() if s["route_id"] == rid]
    return list_response(records)


@bp.post("/delivery-routes/<rid>/dispatch")
@require_roles("OpsManager")
def dispatch_route(rid):
    route = _get_route(rid)
    if route["status"] != "PLANNED":
        raise ApiError(
            409, ERR_INVALID_STATE, "Only a PLANNED route can be dispatched."
        )
    stops = [
        s
        for s in db.delivery_stops.values()
        if s["route_id"] == route["id"] and s["outcome"] == "SCHEDULED"
    ]
    if not stops:
        raise ApiError(409, ERR_EMPTY_ROUTE, "No SCHEDULED stops on this route.")
    # Route minimum allocation: stop subtotal = sum of line extensions over the
    # stop's order lines still pending delivery (SHORTED lines are excluded, so
    # a shortfall reduces the subtotal). Inclusive >= boundary for INCLUDED.
    for stop in sorted(stops, key=lambda s: s["_seq"]):
        subtotal = sum(
            li["line_extension_cents"]
            for li in db.order_items.values()
            if li["standing_order_id"] == stop["standing_order_id"]
            and li["fulfillment"] in ("PLANNED", "ALLOCATED", "DELIVERED")
        )
        stop["stop_subtotal_cents"] = subtotal
        stop["outcome"] = (
            "INCLUDED"
            if subtotal >= route["min_stop_subtotal_cents"]
            else "SKIPPED"
        )
        touch(stop)
    route["status"] = "DISPATCHED"
    touch(route)
    return success(serialize(route), "object", 200)


@bp.post("/delivery-routes/<rid>/complete")
@require_roles("OpsManager")
def complete_route(rid):
    route = _get_route(rid)
    if route["status"] != "DISPATCHED":
        raise ApiError(
            409, ERR_INVALID_STATE, "Only a DISPATCHED route can be completed."
        )
    included = [
        s
        for s in db.delivery_stops.values()
        if s["route_id"] == route["id"] and s["outcome"] == "INCLUDED"
    ]
    for stop in included:
        resolved = any(
            c["delivery_stop_id"] == stop["id"]
            and c["status"] in ("APPROVED", "REJECTED")
            for c in db.spoilage_credits.values()
        )
        if stop["outcome"] == "INCLUDED" and not resolved:
            raise ApiError(
                409,
                ERR_INVALID_STATE,
                "Every INCLUDED stop must be DELIVERED or have a resolved credit.",
            )
    route["status"] = "COMPLETED"
    touch(route)
    return success(serialize(route), "object", 200)


@bp.get("/delivery-stops")
@require_roles(*RW)
def list_stops():
    customer_id = request.args.get("customer_id")
    standing_order_id = request.args.get("standing_order_id")
    outcome = request.args.get("outcome")
    records = list(db.delivery_stops.values())
    if customer_id is not None:
        records = [r for r in records if r["customer_id"] == customer_id]
    if standing_order_id is not None:
        records = [r for r in records if r["standing_order_id"] == standing_order_id]
    if outcome is not None:
        records = [r for r in records if r["outcome"] == outcome]
    return list_response(records)


@bp.get("/delivery-stops/<sid>")
@require_roles(*RW)
def get_stop(sid):
    return success(serialize(_get_stop(sid)), "object", 200)


@bp.post("/delivery-stops/<sid>/deliver")
@require_roles("OpsManager")
def deliver_stop(sid):
    stop = _get_stop(sid)
    route = db.delivery_routes.get(stop["route_id"])
    if route is None or route["status"] != "DISPATCHED":
        raise ApiError(
            409, ERR_ROUTE_NOT_DISPATCHED, "Route is not in DISPATCHED status."
        )
    if stop["outcome"] != "INCLUDED":
        raise ApiError(
            409, ERR_INVALID_STATE, "Only an INCLUDED stop can be delivered."
        )
    stop["outcome"] = "DELIVERED"
    touch(stop)
    # Flip the stop's order lines to DELIVERED; opens the spoilage window.
    for li in db.order_items.values():
        if li["standing_order_id"] == stop["standing_order_id"] and li[
            "fulfillment"
        ] in ("PLANNED", "ALLOCATED"):
            li["fulfillment"] = "DELIVERED"
            touch(li)
    return success(serialize(stop), "object", 200)


@bp.post("/delivery-stops/<sid>/skip")
@require_roles("OpsManager")
def skip_stop(sid):
    stop = _get_stop(sid)
    if stop["outcome"] != "SCHEDULED":
        raise ApiError(
            409, ERR_INVALID_STATE, "Only a SCHEDULED stop can be skipped."
        )
    # Skipping is not a credit event: lines stay ALLOCATED and roll forward.
    stop["outcome"] = "SKIPPED"
    touch(stop)
    return success(serialize(stop), "object", 200)
