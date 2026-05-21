"""Route lifecycle endpoints."""
import copy

from flask import Blueprint

from .. import store
from ..auth import authed
from ..envelope import success_empty, success_object
from ..errors import raise_error
from ..serializers import serialize_route, serialize_route_stop
from ..services.route_planner import (
    assign_planned_times,
    recompute_route_derived,
    stops_for_route_sorted,
)
from ._helpers import (
    get_json_body,
    is_planned_date,
    require,
)


bp = Blueprint("routes", __name__)


@bp.post("/routes")
@authed(["Dispatcher"])
def create_route(user_id, user_role):
    body = get_json_body()
    center_id = require(body, "center_id")
    driver_id = require(body, "driver_id")
    planned_date = require(body, "planned_date")
    if not is_planned_date(planned_date):
        raise_error("ERR_REFERENCE_NOT_FOUND", "planned_date must be YYYY-MM-DD")
    with store.lock:
        if center_id not in store.transit_centers:
            raise_error("ERR_REFERENCE_NOT_FOUND", "center_id not found")
        if driver_id not in store.drivers:
            raise_error("ERR_REFERENCE_NOT_FOUND", "driver_id not found")
        route = {
            "center_id": center_id,
            "driver_id": driver_id,
            "planned_date": planned_date,
            "status": "PLANNED",
            "total_distance_km": 0,
            "stop_count": 0,
            "hazmat_present": False,
        }
        store.stamp_create(route)
        store.routes[route["id"]] = route
        return success_object(serialize_route(route), status=201)


@bp.get("/routes/<rid>")
@authed(["Dispatcher", "Driver", "ComplianceOfficer"])
def read_route(user_id, user_role, rid):
    with store.lock:
        route = store.routes.get(rid)
        if not route:
            raise_error("ERR_NOT_FOUND", "route not found")
        if user_role == "Driver" and route["driver_id"] != user_id:
            raise_error("ERR_FORBIDDEN")
        return success_object(serialize_route(route))


@bp.post("/routes/<rid>/stops")
@authed(["Dispatcher"])
def add_stop(user_id, user_role, rid):
    body = get_json_body()
    parcel_id = require(body, "parcel_id")
    with store.lock:
        route = store.routes.get(rid)
        if not route:
            raise_error("ERR_NOT_FOUND", "route not found")
        if route["status"] != "PLANNED":
            raise_error("ERR_ROUTE_NOT_PLANNED")
        parcel = store.parcels.get(parcel_id)
        if not parcel:
            raise_error("ERR_REFERENCE_NOT_FOUND", "parcel_id not found")
        # If parcel is already on a route while ON_VEHICLE -> uniqueness violation.
        if parcel["status"] == "ON_VEHICLE":
            raise_error("ERR_PARCEL_ALREADY_ON_ROUTE")
        if parcel["status"] != "SORTED":
            raise_error("ERR_INVALID_STATE", "parcel must be SORTED to load")
        # Hazmat driver endorsement check
        if parcel.get("hazmat_class", "NONE") != "NONE":
            driver = store.drivers.get(route["driver_id"])
            if not driver or not driver.get("hazmat_endorsement", False):
                raise_error("ERR_DRIVER_NO_HAZMAT_ENDORSEMENT")

        # Atomically: tentatively add the stop, run time-assignment. If feasibility
        # fails, roll back.
        existing_stops = stops_for_route_sorted(rid)
        new_seq = len(existing_stops) + 1

        tentative_stop = {
            "route_id": rid,
            "parcel_id": parcel_id,
            "sequence": new_seq,
            "planned_arrival": None,
            "planned_departure": None,
            "status": "PLANNED",
        }
        store.stamp_lightweight_create(tentative_stop)

        # Snapshot for rollback
        snapshot_stops = {sid: copy.deepcopy(s) for sid, s in store.route_stops.items()}
        snapshot_parcel_status = parcel["status"]
        snapshot_parcel_updated = parcel.get("updated_at")
        snapshot_parcel_version = parcel.get("version")

        store.route_stops[tentative_stop["id"]] = tentative_stop
        new_sequence = stops_for_route_sorted(rid)
        try:
            assign_planned_times(route, new_sequence)
        except Exception:
            # Roll back
            store.route_stops.clear()
            store.route_stops.update(snapshot_stops)
            raise

        parcel["status"] = "ON_VEHICLE"
        store.stamp_update(parcel)
        recompute_route_derived(route)
        store.stamp_update(route)
        return success_object(serialize_route_stop(tentative_stop), status=201)


@bp.delete("/routes/<rid>/stops/<sid>")
@authed(["Dispatcher"])
def delete_stop(user_id, user_role, rid, sid):
    with store.lock:
        route = store.routes.get(rid)
        if not route:
            raise_error("ERR_NOT_FOUND", "route not found")
        stop = store.route_stops.get(sid)
        if not stop or stop["route_id"] != rid:
            raise_error("ERR_NOT_FOUND", "stop not found")
        if route["status"] != "PLANNED":
            raise_error("ERR_ROUTE_NOT_PLANNED")
        parcel = store.parcels.get(stop["parcel_id"])
        store.route_stops.pop(sid, None)

        # Re-sequence remaining stops to keep them 1..N
        remaining = stops_for_route_sorted(rid)
        for idx, s in enumerate(remaining, start=1):
            s["sequence"] = idx
        # Re-run time assignment on remaining stops; on infeasibility, raise.
        if remaining:
            assign_planned_times(route, remaining)

        if parcel and parcel["status"] == "ON_VEHICLE":
            parcel["status"] = "SORTED"
            store.stamp_update(parcel)
        recompute_route_derived(route)
        store.stamp_update(route)
        return success_empty(204)


@bp.post("/routes/<rid>/dispatch")
@authed(["Dispatcher"])
def dispatch_route(user_id, user_role, rid):
    with store.lock:
        route = store.routes.get(rid)
        if not route:
            raise_error("ERR_NOT_FOUND", "route not found")
        if route["status"] != "PLANNED":
            raise_error("ERR_INVALID_STATE", "route must be PLANNED")
        if int(route.get("stop_count", 0)) < 1:
            raise_error("ERR_INVALID_STATE", "route has no stops")
        driver = store.drivers.get(route["driver_id"])
        if not driver:
            raise_error("ERR_REFERENCE_NOT_FOUND", "driver missing")
        if driver["status"] != "ON_DUTY":
            raise_error("ERR_INVALID_STATE", "driver must be ON_DUTY")
        if route.get("hazmat_present") and not driver.get("hazmat_endorsement", False):
            raise_error("ERR_DRIVER_NO_HAZMAT_ENDORSEMENT")

        # Atomic dispatch -> in_progress
        route["status"] = "IN_PROGRESS"
        driver["status"] = "ON_ROUTE"
        store.stamp_update(driver)
        # Cascade parcels ON_VEHICLE -> OUT_FOR_DELIVERY
        for stop in stops_for_route_sorted(rid):
            parcel = store.parcels.get(stop["parcel_id"])
            if parcel and parcel["status"] == "ON_VEHICLE":
                parcel["status"] = "OUT_FOR_DELIVERY"
                store.stamp_update(parcel)
        store.stamp_update(route)
        return success_object(serialize_route(route))


@bp.post("/routes/<rid>/close")
@authed(["Driver"])
def close_route(user_id, user_role, rid):
    with store.lock:
        route = store.routes.get(rid)
        if not route:
            raise_error("ERR_NOT_FOUND", "route not found")
        if route["driver_id"] != user_id:
            raise_error("ERR_FORBIDDEN")
        if route["status"] != "IN_PROGRESS":
            raise_error("ERR_INVALID_STATE", "route must be IN_PROGRESS")
        for stop in stops_for_route_sorted(rid):
            if stop["status"] not in ("COMPLETED", "FAILED", "SKIPPED"):
                raise_error("ERR_INVALID_STATE", "route has unfinished stops")

        route["status"] = "CLOSED"
        driver = store.drivers.get(route["driver_id"])
        if driver:
            driver["status"] = "RETURNED"
            store.stamp_update(driver)
        # Any parcel still OUT_FOR_DELIVERY -> EXCEPTION as NO_ONE_HOME
        # (PRD §3.4 close clause). But scaffold says the close precondition is that
        # every stop is in {COMPLETED, FAILED, SKIPPED} so parcels are already past
        # OUT_FOR_DELIVERY. Still handle defensively.
        for stop in stops_for_route_sorted(rid):
            parcel = store.parcels.get(stop["parcel_id"])
            if parcel and parcel["status"] == "OUT_FOR_DELIVERY":
                parcel["status"] = "EXCEPTION"
                parcel["redelivery_attempts"] = int(parcel.get("redelivery_attempts", 0)) + 1
                parcel["last_attempt_outcome"] = "NO_ONE_HOME"
                store.stamp_update(parcel)
        store.stamp_update(route)
        return success_object(serialize_route(route))


@bp.post("/routes/<rid>/cancel")
@authed(["Dispatcher"])
def cancel_route(user_id, user_role, rid):
    with store.lock:
        route = store.routes.get(rid)
        if not route:
            raise_error("ERR_NOT_FOUND", "route not found")
        if route["status"] != "PLANNED":
            raise_error("ERR_ROUTE_NOT_PLANNED")

        stops = stops_for_route_sorted(rid)
        for stop in stops:
            parcel = store.parcels.get(stop["parcel_id"])
            if parcel and parcel["status"] == "ON_VEHICLE":
                parcel["status"] = "SORTED"
                store.stamp_update(parcel)
            store.route_stops.pop(stop["id"], None)
        route["status"] = "CANCELLED"
        route["hazmat_present"] = False
        route["stop_count"] = 0
        route["total_distance_km"] = 0
        store.stamp_update(route)
        return success_object(serialize_route(route))
