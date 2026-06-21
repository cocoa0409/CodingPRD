from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, now_iso
from middleware import require_roles
from response import success_object, success_array
from services import calc
from services.common import (
    get_json_body, parse_pagination, paginate,
    require_str, require_int_min,
    get_route_or_404, get_driver_or_404, get_center_or_404,
)
from services.serialize import serialize_route

bp = Blueprint("delivery_routes", __name__)


@bp.post("/delivery/routes")
@require_roles("DispatchManager")
def create_route():
    body = get_json_body()
    driver_id = require_str(body, "driver_id")
    origin_center_id = require_str(body, "origin_center_id")
    service_date = require_str(body, "service_date")
    max_stops = require_int_min(body, "max_stops", 1)
    # FK existence (body refs)
    get_driver_or_404(driver_id)
    get_center_or_404(origin_center_id)

    ts = now_iso()
    rid = db.new_id()
    route = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "driver_id": driver_id,
        "origin_center_id": origin_center_id,
        "service_date": service_date,
        "max_stops": max_stops,
        "planned_weight_kg": 0,
        "committed_weight_kg": 0,
        "stop_count": 0,
        "status": "PLANNING",
    }
    db.routes[rid] = route
    return success_object(serialize_route(route), 201)


@bp.get("/delivery/routes")
@require_roles("DispatchManager", "Driver")
def list_routes():
    limit, offset = parse_pagination()
    driver_id = request.args.get("driver_id")
    origin_center_id = request.args.get("origin_center_id")
    items = list(db.routes.values())
    if driver_id is not None:
        items = [r for r in items if r["driver_id"] == driver_id]
    if origin_center_id is not None:
        items = [r for r in items if r["origin_center_id"] == origin_center_id]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([serialize_route(r) for r in page], limit, offset, total)


@bp.get("/delivery/routes/<route_id>")
@require_roles("DispatchManager", "Driver")
def get_route(route_id):
    route = get_route_or_404(route_id)
    return success_object(serialize_route(route), 200)


@bp.get("/delivery/routes/<route_id>/manifest")
@require_roles("DispatchManager")
def route_manifest(route_id):
    route = get_route_or_404(route_id)
    total, stop_count = calc.compute_manifest_total(route)
    return success_object({
        "route_id": route["id"],
        "stop_count": stop_count,
        "total_handling_fee_cents": total,
    }, 200)


@bp.post("/delivery/routes/<route_id>/dispatch")
@require_roles("DispatchManager")
def dispatch_route(route_id):
    route = get_route_or_404(route_id)
    body = get_json_body()
    # expected_route_version is required, integer
    if "expected_route_version" not in body or isinstance(body.get("expected_route_version"), bool) \
            or not isinstance(body.get("expected_route_version"), int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "expected_route_version must be an integer.")
    expected = body["expected_route_version"]

    # state precondition
    if route["status"] != "PLANNING":
        raise ApiError(errors.ERR_ROUTE_NOT_PLANNING, 409, "Route not in PLANNING.")

    # recompute metrics for an accurate committed_weight view
    calc.recompute_route_metrics(route)

    # at least one non-CANCELLED stop
    active_stops = [s for s in db.stops.values()
                    if s["route_id"] == route["id"] and s["status"] != "CANCELLED"]
    if not active_stops:
        raise ApiError(errors.ERR_ROUTE_EMPTY, 409, "Route has no non-CANCELLED stop.")

    driver = db.drivers.get(route["driver_id"])
    # driver must be ACTIVE
    if driver is None or driver["status"] != "ACTIVE":
        raise ApiError(errors.ERR_DRIVER_SUSPENDED, 409, "Driver is suspended.")

    # vehicle capacity
    if route["committed_weight_kg"] > driver["vehicle_capacity_kg"]:
        raise ApiError(errors.ERR_VEHICLE_CAPACITY_EXCEEDED, 409, "Committed weight exceeds vehicle capacity.")

    # hazmat: any stop's parcel hazmat requires certified driver
    has_hazmat = False
    for s in active_stops:
        p = db.parcels.get(s["parcel_id"])
        if p and p["hazmat_class"] != "NONE":
            has_hazmat = True
            break
    if has_hazmat and not driver["hazmat_certified"]:
        raise ApiError(errors.ERR_DRIVER_NOT_HAZMAT_CERTIFIED, 409, "Driver not hazmat certified.")

    # double booking: driver has another DISPATCHED route on same service_date
    for r in db.routes.values():
        if r["id"] == route["id"]:
            continue
        if r["driver_id"] == driver["id"] and r["status"] == "DISPATCHED" \
                and r["service_date"] == route["service_date"]:
            raise ApiError(errors.ERR_DRIVER_DOUBLE_BOOKED, 409, "Driver already dispatched that day.")

    # OCC last
    if expected != route["version"]:
        raise ApiError(errors.ERR_STALE_ROUTE_VERSION, 412, "Stale route version.")

    # all PENDING stops -> OUT_FOR_DELIVERY
    for s in active_stops:
        if s["status"] == "PENDING":
            s["status"] = "OUT_FOR_DELIVERY"
            s["updated_at"] = now_iso()
            s["version"] += 1

    route["status"] = "DISPATCHED"
    route["updated_at"] = now_iso()
    route["version"] += 1
    return success_object(serialize_route(route), 200)


@bp.post("/delivery/routes/<route_id>/complete")
@require_roles("DispatchManager")
def complete_route(route_id):
    route = get_route_or_404(route_id)
    if route["status"] != "DISPATCHED":
        raise ApiError(errors.ERR_ROUTE_NOT_DISPATCHED, 409, "Route not in DISPATCHED.")
    open_states = {"OUT_FOR_DELIVERY", "ATTEMPTED", "REDELIVERY_SCHEDULED"}
    for s in db.stops.values():
        if s["route_id"] == route["id"] and s["status"] in open_states:
            raise ApiError(errors.ERR_OPEN_STOPS_REMAIN, 409, "Open stops remain.")
    route["status"] = "COMPLETED"
    route["updated_at"] = now_iso()
    route["version"] += 1
    return success_object(serialize_route(route), 200)


@bp.post("/delivery/routes/<route_id>/cancel")
@require_roles("DispatchManager")
def cancel_route(route_id):
    route = get_route_or_404(route_id)
    if route["status"] != "PLANNING":
        raise ApiError(errors.ERR_ROUTE_NOT_CANCELLABLE, 409, "Route not cancellable.")

    origin_center = db.transit_centers.get(route["origin_center_id"])
    for s in db.stops.values():
        if s["route_id"] != route["id"] or s["status"] == "CANCELLED":
            continue
        s["status"] = "CANCELLED"
        s["updated_at"] = now_iso()
        s["version"] += 1
        parcel = db.parcels.get(s["parcel_id"])
        if parcel is not None and parcel["status"] == "ROUTED":
            parcel["status"] = "SORTED"
            parcel["sorted_at_center_id"] = route["origin_center_id"]
            parcel["updated_at"] = now_iso()
            parcel["version"] += 1

    if origin_center is not None:
        calc.recompute_center_sorted_count(origin_center)
        origin_center["updated_at"] = now_iso()
        origin_center["version"] += 1

    calc.recompute_route_metrics(route)
    route["status"] = "CANCELLED"
    route["updated_at"] = now_iso()
    route["version"] += 1
    return success_object(serialize_route(route), 200)
