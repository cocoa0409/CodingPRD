"""Route, RouteStop, and SoiledCart endpoints."""

from flask import Blueprint

import db
import services
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ROUTE_HAS_NO_STOPS,
    ERR_ROUTE_STOPS_OPEN,
    ERR_ROUTE_STOPS_UNRESOLVED,
    ERR_ROUTE_DISCREPANCIES_OPEN,
    ERR_ROUTE_NOT_DISPATCHED,
    ERR_EMPTY_PICKUP,
    ERR_DUPLICATE_CART_TAG,
    ERR_STOP_NOT_PICKED_UP,
    ERR_CART_NOT_VOIDABLE,
)
from response import success, list_response
from util import (
    PLANT_SIDE,
    authenticate,
    require_roles,
    body_json,
    field,
    path_get,
    ref_get,
    filter_eq,
    round2,
    D,
)

bp = Blueprint("transit", __name__)

DRIVER = {"RouteDriver"}


@bp.route("/plants/<pid>/routes", methods=["POST"])
def create_route(pid):
    data = body_json()
    service_date = field(data, "service_date", "date")
    driver_name = field(data, "driver_name", "s")
    auth = authenticate()
    require_roles(auth, DRIVER)
    plant = path_get(db.plants, pid)
    route = db.new_entity()
    route.update(
        {
            "plant_id": plant["id"],
            "service_date": service_date,
            "driver_name": driver_name,
            "status": "PLANNED",
        }
    )
    db.routes[route["id"]] = route
    return success(route, 201)


@bp.route("/plants/<pid>/routes", methods=["GET"])
def list_routes(pid):
    auth = authenticate()
    require_roles(auth, PLANT_SIDE)
    plant = path_get(db.plants, pid)
    items = [r for r in db.sorted_all(db.routes) if r["plant_id"] == plant["id"]]
    items = filter_eq(items, "status", "status")
    items = filter_eq(items, "service_date", "service_date")
    return list_response(items)


@bp.route("/routes/<rid>", methods=["GET"])
def get_route(rid):
    auth = authenticate()
    require_roles(auth, PLANT_SIDE)
    return success(path_get(db.routes, rid))


@bp.route("/routes/<rid>/dispatch", methods=["POST"])
def dispatch_route(rid):
    auth = authenticate()
    require_roles(auth, DRIVER)
    route = path_get(db.routes, rid)
    if route["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Route is not PLANNED")
    stops = [s for s in db.stops.values() if s["route_id"] == route["id"]]
    if not any(s["status"] == "SCHEDULED" for s in stops):
        raise ApiError(ERR_ROUTE_HAS_NO_STOPS, 409, "Dispatch requires at least one SCHEDULED stop")
    route["status"] = "DISPATCHED"
    db.touch(route)
    return success(route)


@bp.route("/routes/<rid>/complete", methods=["POST"])
def complete_route(rid):
    auth = authenticate()
    require_roles(auth, DRIVER)
    route = path_get(db.routes, rid)
    if route["status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, 409, "Route is not DISPATCHED")
    stops = [s for s in db.stops.values() if s["route_id"] == route["id"]]
    if not all(s["status"] in ("PICKED_UP", "DELIVERED", "CLOSED", "DISPUTED") for s in stops):
        raise ApiError(ERR_ROUTE_STOPS_OPEN, 409, "Every stop must be past pickup to complete")
    route["status"] = "COMPLETED"
    db.touch(route)
    return success(route)


@bp.route("/routes/<rid>/reconcile", methods=["POST"])
def reconcile_route(rid):
    auth = authenticate()
    require_roles(auth, DRIVER)
    route = path_get(db.routes, rid)
    if route["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, 409, "Route is not COMPLETED")
    stops = [s for s in db.stops.values() if s["route_id"] == route["id"]]
    if not all(s["status"] in ("CLOSED", "DISPUTED") for s in stops):
        raise ApiError(ERR_ROUTE_STOPS_UNRESOLVED, 409, "Every stop must be CLOSED or DISPUTED")
    stop_ids = {s["id"] for s in stops}
    for d in db.deliveries.values():
        if d["stop_id"] not in stop_ids:
            continue
        for x in db.discrepancies.values():
            if x["delivery_id"] == d["id"] and x["status"] in ("FILED", "UNDER_REVIEW", "APPROVED"):
                raise ApiError(
                    ERR_ROUTE_DISCREPANCIES_OPEN, 409, "Open discrepancies block reconciliation"
                )
    route["status"] = "RECONCILED"
    db.touch(route)
    return success(route)


@bp.route("/routes/<rid>/stops", methods=["POST"])
def create_stop(rid):
    data = body_json()
    customer_id = field(data, "customer_id", "s")
    seq = field(data, "sequence_index", "i", minv=1)
    declared = field(data, "declared_soiled_weight_lb", "n", minv=0)
    auth = authenticate()
    require_roles(auth, DRIVER)
    route = path_get(db.routes, rid)
    cust = ref_get(db.customers, customer_id)
    stop = db.new_entity()
    stop.update(
        {
            "route_id": route["id"],
            "customer_id": cust["id"],
            "sequence_index": seq,
            "declared_soiled_weight_lb": declared,
            "actual_soiled_weight_lb": 0,
            "status": "SCHEDULED",
        }
    )
    db.stops[stop["id"]] = stop
    return success(stop, 201)


@bp.route("/routes/<rid>/stops", methods=["GET"])
def list_stops(rid):
    auth = authenticate()
    require_roles(auth, PLANT_SIDE)
    route = path_get(db.routes, rid)
    items = [s for s in db.sorted_all(db.stops) if s["route_id"] == route["id"]]
    return list_response(items)


@bp.route("/stops/<sid>", methods=["GET"])
def get_stop(sid):
    auth = authenticate()
    require_roles(auth, PLANT_SIDE)
    return success(path_get(db.stops, sid))


@bp.route("/stops/<sid>/arrive", methods=["POST"])
def arrive_stop(sid):
    auth = authenticate()
    require_roles(auth, DRIVER)
    stop = path_get(db.stops, sid)
    if stop["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Stop is not SCHEDULED")
    route = db.routes.get(stop["route_id"])
    if not route or route["status"] != "DISPATCHED":
        raise ApiError(ERR_ROUTE_NOT_DISPATCHED, 409, "Parent route is not DISPATCHED")
    stop["status"] = "ARRIVED"
    db.touch(stop)
    return success(stop)


@bp.route("/stops/<sid>/pickup", methods=["POST"])
def pickup_stop(sid):
    data = body_json()
    if "carts" not in data or not isinstance(data["carts"], list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field carts must be a list")
    carts_in = data["carts"]
    for entry in carts_in:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Each cart entry must be an object")
        field(entry, "cart_tag", "s")
        field(entry, "scale_weight_lb", "n", minv=0)
    auth = authenticate()
    require_roles(auth, DRIVER)
    stop = path_get(db.stops, sid)
    if stop["status"] != "ARRIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Stop is not ARRIVED")
    if len(carts_in) == 0:
        raise ApiError(ERR_EMPTY_PICKUP, 422, "payload.carts must be non-empty")
    seen = set()
    for entry in carts_in:
        if entry["cart_tag"] in seen:
            raise ApiError(ERR_DUPLICATE_CART_TAG, 409, "Duplicate cart_tag within the stop")
        seen.add(entry["cart_tag"])
    for entry in carts_in:
        cart = db.new_entity()
        cart.update(
            {
                "stop_id": stop["id"],
                "cart_tag": entry["cart_tag"],
                "scale_weight_lb": entry["scale_weight_lb"],
                "status": "DECLARED",
            }
        )
        db.carts[cart["id"]] = cart
    stop["status"] = "PICKED_UP"
    db.touch(stop)
    cust = db.customers.get(stop["customer_id"])
    services.garment_cascade(cust, "AT_CUSTOMER", "IN_TRANSIT_SOILED")
    return success(stop)


@bp.route("/stops/<sid>/carts", methods=["GET"])
def list_carts(sid):
    auth = authenticate()
    require_roles(auth, PLANT_SIDE)
    stop = path_get(db.stops, sid)
    items = [c for c in db.sorted_all(db.carts) if c["stop_id"] == stop["id"]]
    return list_response(items)


@bp.route("/carts/<cid>", methods=["GET"])
def get_cart(cid):
    auth = authenticate()
    require_roles(auth, PLANT_SIDE)
    return success(path_get(db.carts, cid))


@bp.route("/carts/<cid>/receive", methods=["POST"])
def receive_cart(cid):
    auth = authenticate()
    require_roles(auth, {"PlantOperator"})
    cart = path_get(db.carts, cid)
    if cart["status"] != "DECLARED":
        raise ApiError(ERR_INVALID_STATE, 409, "Cart is not DECLARED")
    stop = db.stops.get(cart["stop_id"])
    if not stop or stop["status"] not in ("PICKED_UP", "DELIVERED", "DISPUTED"):
        raise ApiError(ERR_STOP_NOT_PICKED_UP, 409, "Stop must be PICKED_UP or later")
    cart["status"] = "RECEIVED"
    db.touch(cart)
    total = sum(
        (D(c["scale_weight_lb"]) for c in db.carts.values() if c["stop_id"] == stop["id"] and c["status"] in ("RECEIVED", "SORTED")),
        D(0),
    )
    stop["actual_soiled_weight_lb"] = float(round2(total))
    db.touch(stop)
    cust = db.customers.get(stop["customer_id"])
    services.garment_cascade(cust, "IN_TRANSIT_SOILED", "SOILED_RECEIVED")
    return success(cart)


@bp.route("/carts/<cid>/void", methods=["POST"])
def void_cart(cid):
    auth = authenticate()
    require_roles(auth, {"PlantOperator"})
    cart = path_get(db.carts, cid)
    if cart["status"] != "DECLARED":
        raise ApiError(ERR_CART_NOT_VOIDABLE, 409, "Only DECLARED carts may be voided")
    cart["status"] = "VOIDED"
    db.touch(cart)
    return success(cart)
