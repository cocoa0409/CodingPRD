"""CarrierRoute and ConsolidationTote endpoints."""

from flask import Blueprint, request

from db import store, stamp, touch
from errors import ApiError, invalid_state, already_terminal
from services import (
    TOTE_MAX_UNITS, TOTE_MAX_WEIGHT_GRAMS,
    ser_route, ser_tote, ser_order, get_or_404, tote_manifest, tote_members,
)
from util import (
    require_roles, respond, body, req_str, req_int, req_field, paginate, is_int,
)

bp = Blueprint("freight", __name__)


def _own_tote_location(uid, role, tote):
    if role == "LocationOperator" and tote["location_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "LocationOperator may act only at its own location")


# ------------------------------------------------------------ carrier routes -
@bp.post("/carrier-routes")
def create_route():
    require_roles("CarrierDispatcher", "PlatformAdmin")
    b = body(required=True)
    origin = req_str(b, "origin_location_id")
    destination = req_str(b, "destination_facility")
    capacity = req_int(b, "weight_capacity_grams")
    if capacity <= 0:
        from errors import bad_request
        bad_request("weight_capacity_grams must be > 0")
    get_or_404("locations", origin)
    route = {
        "origin_location_id": origin,
        "destination_facility": destination,
        "weight_capacity_grams": capacity,
        "status": "PLANNED",
    }
    stamp(route)
    store["routes"][route["id"]] = route
    return respond(ser_route(route), 201)


@bp.get("/carrier-routes/<rid>")
def get_route(rid):
    require_roles("CarrierDispatcher", "PlatformAdmin", "LocationOperator",
                  "SupportAgent")
    return respond(ser_route(get_or_404("routes", rid)))


@bp.get("/carrier-routes")
def list_routes():
    require_roles("CarrierDispatcher", "PlatformAdmin")
    items = list(store["routes"].values())
    origin = request.args.get("origin_location_id")
    status = request.args.get("status")
    if origin is not None:
        items = [r for r in items if r["origin_location_id"] == origin]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items)
    return respond([ser_route(r) for r in page], page=meta)


def _route_state(route, allowed, action):
    if route["status"] in ("ARRIVED", "CANCELLED"):
        already_terminal("Route is in a terminal state")
    if route["status"] not in allowed:
        invalid_state("Route cannot be %sed from %s" % (action, route["status"]))


@bp.post("/carrier-routes/<rid>/dispatch")
def dispatch_route(rid):
    require_roles("CarrierDispatcher")
    route = get_or_404("routes", rid)
    _route_state(route, ("PLANNED",), "dispatch")
    route["status"] = "DISPATCHED"
    touch(route)
    return respond(ser_route(route))


@bp.post("/carrier-routes/<rid>/arrive")
def arrive_route(rid):
    require_roles("CarrierDispatcher")
    route = get_or_404("routes", rid)
    _route_state(route, ("DISPATCHED",), "arrive")
    route["status"] = "ARRIVED"
    touch(route)
    return respond(ser_route(route))


@bp.post("/carrier-routes/<rid>/cancel")
def cancel_route(rid):
    require_roles("CarrierDispatcher")
    route = get_or_404("routes", rid)
    _route_state(route, ("PLANNED",), "cancel")
    for t in store["totes"].values():
        if t["route_id"] == rid and t["status"] in ("SEALED", "DISPATCHED"):
            raise ApiError("ERR_ROUTE_HAS_LIVE_TOTE", 409,
                           "Route cancel blocked by a SEALED or DISPATCHED tote")
    route["status"] = "CANCELLED"
    touch(route)
    return respond(ser_route(route))


# ------------------------------------------------------- consolidation totes -
@bp.post("/consolidation-totes")
def create_tote():
    uid, role = require_roles("LocationOperator")
    b = body(required=True)
    route_id = req_str(b, "route_id")
    location_id = req_str(b, "location_id")
    if uid != location_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "LocationOperator may create totes only at its own location")
    route = get_or_404("routes", route_id)
    location = get_or_404("locations", location_id)
    if route["status"] in ("ARRIVED", "CANCELLED"):
        already_terminal("Route is in a terminal state")
    if route["status"] not in ("PLANNED", "DISPATCHED"):
        invalid_state("Route must be PLANNED or DISPATCHED")
    if location_id != route["origin_location_id"]:
        raise ApiError("ERR_ROUTE_ORIGIN_MISMATCH", 422,
                       "Tote location_id differs from route.origin_location_id")
    if location["status"] != "OPERATIONAL":
        raise ApiError("ERR_LOCATION_NOT_OPERATIONAL", 409,
                       "Location is not OPERATIONAL")
    tote = {
        "route_id": route_id,
        "location_id": location_id,
        "status": "FILLING",
        "sealed_by_user_id": None,
    }
    stamp(tote)
    store["totes"][tote["id"]] = tote
    return respond(ser_tote(tote), 201)


@bp.get("/consolidation-totes/<tid>")
def get_tote(tid):
    uid, role = require_roles("LocationOperator", "PlatformAdmin",
                              "CarrierDispatcher", "SupportAgent")
    tote = get_or_404("totes", tid)
    _own_tote_location(uid, role, tote)
    return respond(ser_tote(tote))


@bp.get("/consolidation-totes")
def list_totes():
    require_roles("LocationOperator", "PlatformAdmin", "CarrierDispatcher")
    items = list(store["totes"].values())
    route_id = request.args.get("route_id")
    location_id = request.args.get("location_id")
    status = request.args.get("status")
    if route_id is not None:
        items = [t for t in items if t["route_id"] == route_id]
    if location_id is not None:
        items = [t for t in items if t["location_id"] == location_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, meta = paginate(items)
    return respond([ser_tote(t) for t in page], page=meta)


@bp.get("/consolidation-totes/<tid>/return-orders")
def list_tote_orders(tid):
    uid, role = require_roles("LocationOperator", "PlatformAdmin",
                              "CarrierDispatcher", "SupportAgent")
    tote = get_or_404("totes", tid)
    _own_tote_location(uid, role, tote)
    page, meta = paginate(tote_members(tid))
    return respond([ser_order(o) for o in page], page=meta)


def _tote_state(tote, allowed, action):
    if tote["status"] == "RECONCILED":
        already_terminal("Tote is RECONCILED")
    if tote["status"] not in allowed:
        invalid_state("Tote cannot be %sed from %s" % (action, tote["status"]))


def _tote_occ(b, tote):
    expected = req_field(b, "expected_tote_version")
    if not is_int(expected):
        from errors import bad_request
        bad_request("expected_tote_version must be an integer")
    if expected != tote["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_tote_version does not match current version")


@bp.post("/consolidation-totes/<tid>/return-orders")
def tote_add_order(tid):
    uid, role = require_roles("LocationOperator")
    tote = get_or_404("totes", tid)
    _own_tote_location(uid, role, tote)
    b = body(required=True)
    order_id = req_str(b, "return_order_id")
    order = get_or_404("orders", order_id)
    _tote_occ(b, tote)
    # Priority 6: order must be DROPPED_OFF.
    if order["status"] in ("REFUND_POSTED", "CANCELLED", "REJECTED_CLOSED"):
        already_terminal("Order is in a terminal state")
    if order["status"] != "DROPPED_OFF":
        invalid_state("Only a DROPPED_OFF order can join a tote")
    # Priority 11: tote FILLING, membership, location match, capacity.
    if tote["status"] != "FILLING":
        raise ApiError("ERR_TOTE_NOT_FILLING", 409,
                       "Membership change requires tote FILLING")
    route = store["routes"][tote["route_id"]]
    if route["status"] not in ("PLANNED", "DISPATCHED"):
        invalid_state("Tote route is no longer PLANNED or DISPATCHED")
    if order.get("tote_id") is not None:
        raise ApiError("ERR_ORDER_ALREADY_IN_TOTE", 409,
                       "Order already has a tote membership")
    if order.get("dropoff_location_id") != tote["location_id"]:
        raise ApiError("ERR_ORDER_NOT_AT_LOCATION", 409,
                       "Order's dropoff_location_id differs from tote location")
    units, weight = tote_manifest(tid)
    if units + order["total_units"] > TOTE_MAX_UNITS:
        raise ApiError("ERR_TOTE_CAPACITY_EXCEEDED", 409,
                       "Add would push manifest_units over 40")
    if weight + order["total_weight_grams"] > TOTE_MAX_WEIGHT_GRAMS:
        raise ApiError("ERR_TOTE_WEIGHT_EXCEEDED", 409,
                       "Add would push manifest_weight_grams over 30000")
    order["tote_id"] = tid
    touch(order)
    touch(tote)
    return respond(ser_tote(tote))


@bp.post("/consolidation-totes/<tid>/return-orders/remove")
def tote_remove_order(tid):
    uid, role = require_roles("LocationOperator")
    tote = get_or_404("totes", tid)
    _own_tote_location(uid, role, tote)
    b = body(required=True)
    order_id = req_str(b, "return_order_id")
    order = get_or_404("orders", order_id)
    _tote_occ(b, tote)
    if tote["status"] != "FILLING":
        raise ApiError("ERR_TOTE_NOT_FILLING", 409,
                       "Membership change requires tote FILLING")
    if order.get("tote_id") != tid:
        raise ApiError("ERR_NOT_FOUND", 404,
                       "Order is not a member of this tote")
    order["tote_id"] = None
    touch(order)
    touch(tote)
    return respond(ser_tote(tote))


@bp.post("/consolidation-totes/<tid>/seal")
def seal_tote(tid):
    uid, role = require_roles("LocationOperator")
    tote = get_or_404("totes", tid)
    _own_tote_location(uid, role, tote)
    _tote_state(tote, ("FILLING",), "seal")
    units, _ = tote_manifest(tid)
    if units < 1:
        raise ApiError("ERR_TOTE_EMPTY", 409, "Seal attempted on an empty tote")
    tote["status"] = "SEALED"
    tote["sealed_by_user_id"] = uid
    touch(tote)
    return respond(ser_tote(tote))


@bp.post("/consolidation-totes/<tid>/unseal")
def unseal_tote(tid):
    uid, role = require_roles("LocationOperator")
    tote = get_or_404("totes", tid)
    _own_tote_location(uid, role, tote)
    _tote_state(tote, ("SEALED",), "unseal")
    tote["status"] = "FILLING"
    tote["sealed_by_user_id"] = None
    touch(tote)
    return respond(ser_tote(tote))


@bp.post("/consolidation-totes/<tid>/dispatch")
def dispatch_tote(tid):
    uid, role = require_roles("LocationOperator")
    tote = get_or_404("totes", tid)
    _own_tote_location(uid, role, tote)
    _tote_state(tote, ("SEALED",), "dispatch")
    route = store["routes"][tote["route_id"]]
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_ROUTE_NOT_DISPATCHED", 409,
                       "Tote dispatch requires route DISPATCHED")
    _, weight = tote_manifest(tid)
    if weight > route["weight_capacity_grams"]:
        raise ApiError("ERR_ROUTE_WEIGHT_EXCEEDED", 422,
                       "Tote manifest weight exceeds route weight capacity")
    tote["status"] = "DISPATCHED"
    touch(tote)
    for o in tote_members(tid):
        if o["status"] == "DROPPED_OFF":
            o["status"] = "IN_TRANSIT"
            touch(o)
    return respond(ser_tote(tote))


@bp.post("/consolidation-totes/<tid>/arrive")
def arrive_tote(tid):
    uid, role = require_roles("CarrierDispatcher", "LocationOperator")
    tote = get_or_404("totes", tid)
    _own_tote_location(uid, role, tote)
    _tote_state(tote, ("DISPATCHED",), "arrive")
    tote["status"] = "ARRIVED"
    touch(tote)
    for o in tote_members(tid):
        if o["status"] == "IN_TRANSIT":
            o["status"] = "INSPECTING"
            touch(o)
    return respond(ser_tote(tote))


@bp.post("/consolidation-totes/<tid>/flag-discrepancy")
def flag_discrepancy(tid):
    require_roles("SupportAgent", "PlatformAdmin")
    tote = get_or_404("totes", tid)
    b = body(required=True)
    req_str(b, "note")
    _tote_state(tote, ("ARRIVED",), "flag")
    tote["status"] = "DISCREPANCY"
    touch(tote)
    return respond(ser_tote(tote))


@bp.post("/consolidation-totes/<tid>/reconcile")
def reconcile_tote(tid):
    uid, role = require_roles("SupportAgent", "LocationOperator")
    tote = get_or_404("totes", tid)
    _own_tote_location(uid, role, tote)
    _tote_state(tote, ("ARRIVED", "DISCREPANCY"), "reconcile")
    tote["status"] = "RECONCILED"
    touch(tote)
    return respond(ser_tote(tote))
