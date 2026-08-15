"""Route + RouteStop endpoints."""
from datetime import date as date_type
from flask import Blueprint

import domain as D
from db import store, mint, touch
from errors import err
from middleware import authorize, ROLES
from response import ok, ok_list
from validate import body, need_str, need_int, need_date, paginate

bp = Blueprint("logistics", __name__)


# ---- Route ----

@bp.post("/plant/routes")
def create_route():
    authorize(["RouteDispatcher"])
    b = body()
    route_code = need_str(b, "route_code")
    route_date = need_date(b, "route_date")
    region = need_str(b, "region")
    vehicle_capacity_cases = need_int(b, "vehicle_capacity_cases")
    if vehicle_capacity_cases <= 0:
        err("ERR_INVALID_REQUEST", 400, "vehicle_capacity_cases must be greater than zero")
    for r in store.routes.values():
        if r["route_code"] == route_code:
            err("ERR_DUPLICATE_CODE", 409, "route_code already exists")
    route = mint()
    route.update({"route_code": route_code, "route_date": route_date, "region": region,
                  "vehicle_capacity_cases": vehicle_capacity_cases,
                  "route_status": "PLANNED"})
    store.routes[route["id"]] = route
    return ok(D.route_json(route), 201)


@bp.get("/plant/routes/<rid>")
def get_route(rid):
    authorize(ROLES)
    return ok(D.route_json(D.get_route(rid)))


@bp.post("/plant/routes/<rid>/dispatch")
def dispatch_route(rid):
    authorize(["RouteDispatcher"])
    route = D.get_route(rid)
    if route["route_status"] != "PLANNED":
        err("ERR_ROUTE_INVALID_STATE", 409, "Route must be PLANNED to dispatch")
    has_allocated = any(s["route_id"] == rid and s["stop_status"] == "ALLOCATED"
                        for s in store.stops.values())
    if not has_allocated:
        err("ERR_ROUTE_EMPTY", 409, "Route has no ALLOCATED stop")
    route["route_status"] = "DISPATCHED"
    touch(route)
    return ok(D.route_json(route))


@bp.post("/plant/routes/<rid>/complete")
def complete_route(rid):
    authorize(["RouteDispatcher"])
    route = D.get_route(rid)
    if route["route_status"] != "DISPATCHED":
        err("ERR_ROUTE_INVALID_STATE", 409, "Route must be DISPATCHED to complete")
    for s in store.stops.values():
        if s["route_id"] == rid and s["stop_status"] not in ("DELIVERED", "SHORTED"):
            err("ERR_UNRESOLVED_STOPS", 409, "All stops must be terminal to complete")
    route["route_status"] = "COMPLETED"
    touch(route)
    return ok(D.route_json(route))


@bp.post("/plant/routes/<rid>/cancel")
def cancel_route(rid):
    authorize(["RouteDispatcher"])
    route = D.get_route(rid)
    if route["route_status"] != "PLANNED":
        err("ERR_ROUTE_INVALID_STATE", 409, "Only a PLANNED route may be cancelled")
    for s in store.stops.values():
        if s["route_id"] == rid and s["stop_status"] == "ALLOCATED":
            D.short_stop(s)
    route["route_status"] = "CANCELLED"
    touch(route)
    return ok(D.route_json(route))


@bp.get("/plant/routes/<rid>/stops")
def route_stops(rid):
    authorize(ROLES)
    D.get_route(rid)
    items = [s for s in store.stops.values() if s["route_id"] == rid]
    page, limit, offset, total = paginate(items, D.stop_json)
    return ok_list(page, limit, offset, total)


# ---- RouteStop ----

@bp.post("/plant/routes/<rid>/stops")
def create_stop(rid):
    authorize(["RouteDispatcher"])
    b = body()
    customer_id = need_str(b, "customer_id")
    pack_order_id = need_str(b, "pack_order_id")
    requested_cases = need_int(b, "requested_cases")
    expected_route_version = need_int(b, "expected_route_version")
    if requested_cases <= 0:
        err("ERR_INVALID_REQUEST", 400, "requested_cases must be greater than zero")
    # existence: path first, then body FKs
    route = D.get_route(rid)
    customer = D.get_customer(customer_id)
    pack = D.get_pack(pack_order_id)
    # state: OCC fires first among the state checks (PRD section 3.9)
    if expected_route_version != route["version"]:
        err("ERR_STALE_VERSION", 412, "expected_route_version does not match route version")
    if route["route_status"] != "PLANNED":
        err("ERR_ROUTE_INVALID_STATE", 409, "Route must be PLANNED to add a stop")
    if pack["pack_status"] != "SEALED":
        err("ERR_PACK_NOT_SEALED", 409, "Pack order must be SEALED to source a stop")
    # business safety: shelf-life gate (integer arithmetic, inclusive boundary)
    run = D.get_run(pack["production_run_id"])
    product = D.get_product(run["product_id"])
    expires_on = date_type.fromisoformat(pack["expires_on"])
    remaining_days = (expires_on - route["route_date"]).days
    if remaining_days * 100 < customer["min_shelf_life_pct"] * product["shelf_life_days"]:
        err("ERR_SHELF_LIFE_INSUFFICIENT", 422,
            "Remaining shelf life below the customer's minimum on route_date")
    # business constraint: route capacity, then pack stock
    open_cases = route["vehicle_capacity_cases"] - D.route_committed_cases(rid)
    if open_cases < requested_cases:
        err("ERR_ROUTE_CAPACITY_EXCEEDED", 422, "requested_cases exceeds route open_cases")
    if D.pack_cases_available(pack) < requested_cases:
        err("ERR_PACK_STOCK_INSUFFICIENT", 422, "requested_cases exceeds pack cases_available")
    # business fiscal: credit, then strict allotment
    if customer["credit_standing"] != "GOOD":
        err("ERR_CUSTOMER_CREDIT_HOLD", 422, "Customer is on credit HOLD")
    window = D.active_strict_window_for_date(route["route_date"])
    allotment = None
    if window is not None:
        allotment = D.find_allotment(window["id"], customer["id"])
        remaining = (allotment["allotted_cases"]
                     - D.allotment_consumed_cases(allotment)) if allotment else 0
        if requested_cases > remaining:
            err("ERR_ALLOTMENT_EXCEEDED", 422,
                "requested_cases exceeds the strict window allotment remaining_cases")
    stop = mint()
    stop.update({
        "route_id": route["id"], "customer_id": customer["id"],
        "pack_order_id": pack["id"], "requested_cases": requested_cases,
        "allocated_cases": requested_cases, "delivered_cases": None,
        "stop_status": "ALLOCATED",
    })
    store.stops[stop["id"]] = stop
    touch(pack)   # cases_available decreased
    touch(route)  # committed_cases increased; version +1
    if allotment is not None:
        touch(allotment)  # consumed_cases increased (derived)
    return ok(D.stop_json(stop), 201)


@bp.get("/plant/stops/<sid>")
def get_stop(sid):
    authorize(ROLES)
    return ok(D.stop_json(D.get_stop(sid)))


@bp.post("/plant/stops/<sid>/deliver")
def deliver_stop(sid):
    authorize(["RouteDispatcher"])
    b = body()
    delivered_cases = need_int(b, "delivered_cases")
    if delivered_cases < 0:
        err("ERR_VALIDATION", 422, "delivered_cases may not be negative")
    stop = D.get_stop(sid)
    if delivered_cases > stop["allocated_cases"]:
        err("ERR_VALIDATION", 422, "delivered_cases may not exceed allocated_cases")
    if stop["stop_status"] != "ALLOCATED":
        err("ERR_STOP_INVALID_STATE", 409, "Stop must be ALLOCATED to deliver")
    route = D.get_route(stop["route_id"])
    if route["route_status"] != "DISPATCHED":
        err("ERR_ROUTE_INVALID_STATE", 409, "Route must be DISPATCHED to deliver a stop")
    stop["delivered_cases"] = delivered_cases
    stop["stop_status"] = "DELIVERED"
    touch(stop)
    return ok(D.stop_json(stop))


@bp.post("/plant/stops/<sid>/short")
def short_stop_endpoint(sid):
    authorize(["RouteDispatcher"])
    stop = D.get_stop(sid)
    if stop["stop_status"] != "ALLOCATED":
        err("ERR_STOP_INVALID_STATE", 409, "Stop must be ALLOCATED to short")
    route = D.get_route(stop["route_id"])
    if route["route_status"] != "PLANNED":
        err("ERR_ROUTE_INVALID_STATE", 409, "Route must be PLANNED to short a stop")
    D.short_stop(stop)
    return ok(D.stop_json(stop))
