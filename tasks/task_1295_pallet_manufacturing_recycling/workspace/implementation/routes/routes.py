"""DeliveryRoute and RouteStop endpoints."""

from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import (
    require_roles, get_json_body, parse_pagination, paginate,
    req_field, opt_field, as_str, as_int, as_number, as_enum, as_datetime,
)
from response import success
from services.calc import (
    compute_provisional_margin, compute_final_margin,
)
from services.helpers import (
    init_common, touch, serialize, serialize_list, sorted_by_creation,
    get_or_404, ref_or_404,
)

bp = Blueprint("routes", __name__)

STOP_TYPES = ("DELIVERY", "PICKUP", "MIXED")


def _route_stops(route_id):
    return [s for s in db.route_stops.values() if s["route_id"] == route_id]


@bp.post("/pallet-ops/routes")
def create_route():
    require_roles("FleetPlanner")
    body = get_json_body()
    as_datetime(req_field(body, "route_date"), "route_date")
    capacity = as_number(
        req_field(body, "trailer_cube_capacity_cuft"), "trailer_cube_capacity_cuft",
        minimum=0, exclusive_min=True,
    )
    planned_miles = as_number(req_field(body, "planned_miles"), "planned_miles", minimum=0, exclusive_min=True)

    route = {
        "route_date": body["route_date"],
        "trailer_cube_capacity_cuft": capacity,
        "cube_used_cuft": 0,
        "planned_miles": planned_miles,
        "provisional_margin_cents": None,
        "final_margin_cents": None,
        "fuel_surcharge_cents": 0,
        "status": "PLAN",
    }
    init_common(route)
    db.routes[route["id"]] = route
    return success(serialize(route), status=201)


@bp.get("/pallet-ops/routes")
def list_routes():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.routes.values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/routes/<rid>")
def get_route(rid):
    require_roles()
    route = get_or_404(db.routes, rid, "DeliveryRoute")
    return success(serialize(route))


@bp.post("/pallet-ops/routes/<rid>/stops")
def add_stop(rid):
    require_roles("FleetPlanner")
    route = get_or_404(db.routes, rid, "DeliveryRoute")
    body = get_json_body()
    stop_sequence = as_int(req_field(body, "stop_sequence"), "stop_sequence", minimum=1)
    stop_type = as_enum(req_field(body, "stop_type"), "stop_type", STOP_TYPES)
    order_id = opt_field(body, "order_id", None)
    order = None
    if order_id is not None:
        if not isinstance(order_id, str):
            raise_err("ERR_INVALID_REQUEST", "order_id must be a string")
        order = ref_or_404(db.orders, order_id, "order_id")
    pickup_customer_id = opt_field(body, "pickup_customer_id", None)
    if pickup_customer_id is not None:
        if not isinstance(pickup_customer_id, str):
            raise_err("ERR_INVALID_REQUEST", "pickup_customer_id must be a string")
        ref_or_404(db.customers, pickup_customer_id, "pickup_customer_id")

    if route["status"] != "PLAN":
        raise_err("ERR_INVALID_STATE", "stops require route PLAN")

    stops = _route_stops(rid)
    if any(s["stop_sequence"] == stop_sequence for s in stops):
        raise_err("ERR_DUPLICATE_STOP_SEQUENCE", "stop_sequence already used on this route")

    # Load cube: sum over the order's ALLOCATED lines of qty * spec unit cube.
    load_cube = 0.0
    if order is not None and stop_type in ("DELIVERY", "MIXED"):
        cube = Decimal(0)
        for line in db.order_lines.values():
            if line["order_id"] == order_id and line["status"] in ("ALLOCATED", "FULFILLED"):
                spec = db.specs.get(line["spec_id"])
                if spec is not None:
                    cube += Decimal(line["quantity"]) * Decimal(str(spec["unit_cube_cuft"]))
        load_cube = float(cube)

    if Decimal(str(route["cube_used_cuft"])) + Decimal(str(load_cube)) > Decimal(
        str(route["trailer_cube_capacity_cuft"])
    ):
        raise_err("ERR_CUBE_OVERFLOW", "Stop load would exceed trailer_cube_capacity_cuft")

    stop = {
        "route_id": rid,
        "stop_sequence": stop_sequence,
        "order_id": order_id,
        "stop_type": stop_type,
        "load_cube_cuft": load_cube,
        "status": "SCHEDULED",
        "pickup_customer_id": pickup_customer_id,
    }
    init_common(stop)
    db.route_stops[stop["id"]] = stop

    route["cube_used_cuft"] = float(
        Decimal(str(route["cube_used_cuft"])) + Decimal(str(load_cube))
    )
    touch(route)
    return success(serialize(stop), status=201)


@bp.get("/pallet-ops/route-stops")
def list_stops():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.route_stops.values())
    route_id = request.args.get("route_id")
    if route_id is not None:
        items = [s for s in items if s["route_id"] == route_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [s for s in items if s.get("order_id") == order_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/route-stops/<sid>")
def get_stop(sid):
    require_roles()
    stop = get_or_404(db.route_stops, sid, "RouteStop")
    return success(serialize(stop))


@bp.post("/pallet-ops/routes/<rid>/dispatch")
def dispatch_route(rid):
    require_roles("FleetPlanner")
    route = get_or_404(db.routes, rid, "DeliveryRoute")
    body = get_json_body()
    # OCC check pinned before state preconditions.
    expected = req_field(body, "expected_route_version")
    expected = as_int(expected, "expected_route_version")
    if expected != route["version"]:
        raise_err(
            "ERR_STALE_VERSION",
            "expected_route_version does not match the route's current version",
        )

    if route["status"] != "PLAN":
        raise_err("ERR_ROUTE_NOT_PLAN", "dispatch requires route PLAN")
    stops = _route_stops(rid)
    if not stops:
        raise_err("ERR_ROUTE_EMPTY", "dispatch requires at least one stop")
    if Decimal(str(route["cube_used_cuft"])) > Decimal(str(route["trailer_cube_capacity_cuft"])):
        raise_err("ERR_CUBE_OVERFLOW", "cube_used_cuft exceeds trailer_cube_capacity_cuft")

    # Every stop's order must be ALLOCATED (delivery-carrying stops).
    for stop in stops:
        if stop["stop_type"] in ("DELIVERY", "MIXED") and stop.get("order_id"):
            order = db.orders.get(stop["order_id"])
            if order is None or order["fulfillment_status"] != "ALLOCATED":
                raise_err(
                    "ERR_ORDER_NOT_ALLOCATED",
                    "dispatch requires every stop order ALLOCATED",
                )

    route["provisional_margin_cents"] = compute_provisional_margin(route, stops)

    # Cross-entity cascade: orders SHIPPED, their ALLOCATED lines FULFILLED.
    for stop in stops:
        if stop["stop_type"] in ("DELIVERY", "MIXED") and stop.get("order_id"):
            order = db.orders.get(stop["order_id"])
            if order is not None and order["fulfillment_status"] == "ALLOCATED":
                order["fulfillment_status"] = "SHIPPED"
                touch(order)
                for line in db.order_lines.values():
                    if line["order_id"] == order["id"] and line["status"] == "ALLOCATED":
                        line["status"] = "FULFILLED"
                        touch(line)

    route["status"] = "DISPATCHED"
    touch(route)
    return success(serialize(route))


@bp.post("/pallet-ops/route-stops/<sid>/arrive")
def arrive_stop(sid):
    require_roles("FleetPlanner")
    stop = get_or_404(db.route_stops, sid, "RouteStop")
    if stop["status"] != "SCHEDULED":
        raise_err("ERR_STOP_NOT_SCHEDULED", "arrive requires stop SCHEDULED")
    route = db.routes.get(stop["route_id"])
    if route is None or route["status"] != "DISPATCHED":
        raise_err("ERR_ROUTE_NOT_DISPATCHED", "arrive requires route DISPATCHED")
    siblings = _route_stops(stop["route_id"])
    for s in siblings:
        if s["stop_sequence"] < stop["stop_sequence"] and s["status"] not in ("COMPLETED", "SKIPPED"):
            raise_err(
                "ERR_STOP_OUT_OF_SEQUENCE",
                "Lower-sequence stops not yet COMPLETED/SKIPPED",
            )
    stop["status"] = "ARRIVED"
    touch(stop)
    return success(serialize(stop))


@bp.post("/pallet-ops/route-stops/<sid>/complete")
def complete_stop(sid):
    require_roles("FleetPlanner")
    stop = get_or_404(db.route_stops, sid, "RouteStop")
    if stop["status"] != "ARRIVED":
        raise_err("ERR_STOP_NOT_ARRIVED", "complete requires stop ARRIVED")

    stop["status"] = "COMPLETED"
    touch(stop)

    # Delivery side effects for DELIVERY/MIXED stops.
    if stop["stop_type"] in ("DELIVERY", "MIXED") and stop.get("order_id"):
        order = db.orders.get(stop["order_id"])
        if order is not None and order["fulfillment_status"] == "SHIPPED":
            # Delivered once all of the order's stops are COMPLETED.
            order_stops = [
                s for s in db.route_stops.values()
                if s.get("order_id") == order["id"]
            ]
            if all(s["status"] == "COMPLETED" for s in order_stops):
                order["fulfillment_status"] = "DELIVERED"
                touch(order)
                delivered_qty = sum(
                    l["quantity"]
                    for l in db.order_lines.values()
                    if l["order_id"] == order["id"] and l["status"] == "FULFILLED"
                )
                customer = db.customers.get(order["customer_id"])
                if customer is not None:
                    customer["pool_units_outstanding"] += delivered_qty
                    touch(customer)
    return success(serialize(stop))


@bp.post("/pallet-ops/route-stops/<sid>/skip")
def skip_stop(sid):
    require_roles("FleetPlanner")
    stop = get_or_404(db.route_stops, sid, "RouteStop")
    if stop["status"] != "SCHEDULED":
        raise_err("ERR_STOP_NOT_SCHEDULED", "skip requires stop SCHEDULED")
    stop["status"] = "SKIPPED"
    touch(stop)
    return success(serialize(stop))


@bp.post("/pallet-ops/routes/<rid>/close")
def close_route(rid):
    require_roles("FleetPlanner")
    route = get_or_404(db.routes, rid, "DeliveryRoute")
    body = get_json_body()
    fuel = req_field(body, "fuel_surcharge_cents")
    fuel = as_int(fuel, "fuel_surcharge_cents", minimum=0)

    if route["status"] != "DISPATCHED":
        raise_err("ERR_ROUTE_NOT_DISPATCHED", "close requires route DISPATCHED")
    stops = _route_stops(rid)
    if any(s["status"] not in ("COMPLETED", "SKIPPED") for s in stops):
        raise_err("ERR_STOPS_OPEN", "Route close blocked by stops not COMPLETED/SKIPPED")

    route["fuel_surcharge_cents"] = fuel
    route["final_margin_cents"] = compute_final_margin(route, stops)
    # provisional_margin_cents retained untouched.
    route["status"] = "CLOSED"
    touch(route)
    return success(serialize(route))


@bp.post("/pallet-ops/routes/<rid>/cancel")
def cancel_route(rid):
    require_roles("FleetPlanner")
    route = get_or_404(db.routes, rid, "DeliveryRoute")
    if route["status"] != "PLAN":
        raise_err("ERR_ROUTE_NOT_PLAN", "cancel requires route PLAN")
    for stop in _route_stops(rid):
        if stop["status"] == "SCHEDULED":
            stop["status"] = "SKIPPED"
            touch(stop)
    route["status"] = "CANCELLED"
    touch(route)
    return success(serialize(route))
