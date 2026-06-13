"""BusTrip endpoints (PRD §3.6, §3.7, §3.8 cascade)."""

from flask import Blueprint, request

from db import DB
from middleware import authenticate, require_role
from response import ok, ok_list
from errors import (
    err, ERR_INVALID_REFERENCE, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_ROUTE_NOT_OPEN, ERR_ASSIGNMENT_NOT_ACTIVE, ERR_DRIVER_DOUBLE_BOOKED,
    ERR_RIDERS_STILL_ONBOARD,
)
from services import validate as v
from services.common import (
    stamp_create, touch, parse_pagination, sorted_by_creation, paginate,
)
from services.domain import (
    bus_trip_public, onboard_count, onboard_set, route_final_sequence,
    next_sequence_after,
)
from services.lookup import get_bus_trip
from services.notify import emit

bp = Blueprint("bus_trips", __name__)


def _trip_driver_id(trip):
    asg = DB.driver_assignments.get(trip["driver_assignment_id"])
    return asg["driver_id"] if asg else None


def _require_trip_driver(p, trip):
    """Driver ownership: acting driver must be the trip's assigned driver."""
    if p.role == "Driver" and _trip_driver_id(trip) != p.user_id:
        raise err(ERR_FORBIDDEN, "Driver does not own this trip")


@bp.post("/bus-trips")
def create_bus_trip():
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    body = v.get_body()

    route_id = v.require_str(body, "route_id")
    driver_assignment_id = v.require_str(body, "driver_assignment_id")

    route = DB.routes.get(route_id)
    asg = DB.driver_assignments.get(driver_assignment_id)
    if route is None or asg is None:
        raise err(ERR_INVALID_REFERENCE, "A body reference does not resolve")
    if asg["route_id"] != route_id:
        raise err(ERR_INVALID_REFERENCE, "driver_assignment does not belong to the trip's route")

    district = DB.districts.get(route["district_id"])
    rec = {
        "route_id": route_id,
        "driver_assignment_id": driver_assignment_id,
        "service_day_index": district["service_day_index"] if district else 0,
        "status": "SCHEDULED",
        "current_stop_sequence": 0,
        "last_lat": None,
        "last_lng": None,
        "incident_count": 0,
        "_on_duty_driver": None,
    }
    stamp_create(rec)
    DB.bus_trips[rec["id"]] = rec
    return ok(bus_trip_public(rec), 201)


@bp.get("/bus-trips/<bus_trip_id>")
def get_bus_trip_ep(bus_trip_id):
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent", "Driver"})
    rec = get_bus_trip(bus_trip_id)
    return ok(bus_trip_public(rec), 200)


@bp.get("/bus-trips")
def list_bus_trips():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent", "Driver"})
    limit, offset = parse_pagination(request.args)

    records = list(DB.bus_trips.values())
    for field in ("route_id", "driver_assignment_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]

    records = sorted_by_creation(records)
    page, total = paginate(records, limit, offset)
    return ok_list([bus_trip_public(r) for r in page], limit, offset, total)


# ---- GPS ping ----------------------------------------------------------------

@bp.post("/bus-trips/<bus_trip_id>/gps")
def gps_ping(bus_trip_id):
    p = authenticate()
    require_role(p, {"Driver"})
    trip = get_bus_trip(bus_trip_id)
    _require_trip_driver(p, trip)
    body = v.get_body()
    lat = v.require_number(body, "lat")
    lng = v.require_number(body, "lng")

    trip["last_lat"] = lat
    trip["last_lng"] = lng
    touch(trip)
    return ok(bus_trip_public(trip), 200)


# ---- Lifecycle ---------------------------------------------------------------

@bp.post("/bus-trips/<bus_trip_id>/start-boarding")
def start_boarding(bus_trip_id):
    p = authenticate()
    require_role(p, {"Driver"})
    trip = get_bus_trip(bus_trip_id)
    _require_trip_driver(p, trip)

    if trip["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "start-boarding requires SCHEDULED")

    route = DB.routes.get(trip["route_id"])
    if route["posture"] not in ("OPEN", "RESTRICTED"):
        raise err(ERR_ROUTE_NOT_OPEN, "route is SUSPENDED")

    asg = DB.driver_assignments.get(trip["driver_assignment_id"])
    if asg is None or asg["status"] != "ACTIVE":
        raise err(ERR_ASSIGNMENT_NOT_ACTIVE, "driver assignment is not ACTIVE")

    driver_id = asg["driver_id"]
    for t in DB.bus_trips.values():
        if t["id"] == trip["id"]:
            continue
        if t["status"] in ("BOARDING", "IN_TRANSIT"):
            other_asg = DB.driver_assignments.get(t["driver_assignment_id"])
            if other_asg and other_asg["driver_id"] == driver_id:
                raise err(ERR_DRIVER_DOUBLE_BOOKED, "driver already in flight")

    trip["status"] = "BOARDING"
    trip["current_stop_sequence"] = 1
    touch(trip)

    driver = DB.drivers.get(driver_id)
    if driver:
        driver["status"] = "ON_DUTY"
        touch(driver)
        trip["_on_duty_driver"] = driver_id

    return ok(bus_trip_public(trip), 200)


@bp.post("/bus-trips/<bus_trip_id>/depart-stop")
def depart_stop(bus_trip_id):
    p = authenticate()
    require_role(p, {"Driver"})
    trip = get_bus_trip(bus_trip_id)
    _require_trip_driver(p, trip)
    body = v.get_body()
    stop_sequence = v.require_int(body, "stop_sequence")

    if trip["status"] not in ("BOARDING", "IN_TRANSIT"):
        raise err(ERR_INVALID_STATE, "depart-stop requires BOARDING or IN_TRANSIT")
    if stop_sequence != trip["current_stop_sequence"]:
        raise err(ERR_INVALID_STATE, "stop_sequence must equal current_stop_sequence")

    final_seq = route_final_sequence(trip["route_id"])
    if trip["status"] == "IN_TRANSIT" and trip["current_stop_sequence"] == final_seq:
        raise err(ERR_INVALID_STATE, "already at the final stop")

    nxt = next_sequence_after(trip["route_id"], trip["current_stop_sequence"])
    if nxt is not None:
        trip["current_stop_sequence"] = nxt
    else:
        # No further stop: advance past the final stop sequence.
        trip["current_stop_sequence"] = trip["current_stop_sequence"] + 1

    trip["status"] = "IN_TRANSIT"
    touch(trip)
    return ok(bus_trip_public(trip), 200)


@bp.post("/bus-trips/<bus_trip_id>/raise-incident")
def raise_incident(bus_trip_id):
    p = authenticate()
    require_role(p, {"Driver"})
    trip = get_bus_trip(bus_trip_id)
    _require_trip_driver(p, trip)

    if trip["status"] not in ("BOARDING", "IN_TRANSIT"):
        raise err(ERR_INVALID_STATE, "raise-incident requires BOARDING or IN_TRANSIT")

    trip["status"] = "INCIDENT_HOLD"
    trip["incident_count"] = trip["incident_count"] + 1
    touch(trip)
    # Route.open_incident is computed live; bump the route as a mutation.
    route = DB.routes.get(trip["route_id"])
    if route:
        touch(route)

    # Notify every onboard student's parent.
    for student_id in onboard_set(trip["id"]):
        student = DB.students.get(student_id)
        if student:
            emit(student["district_id"], student["parent_id"], student_id,
                 trip["id"], "INCIDENT",
                 {"stop_sequence": trip["current_stop_sequence"]})

    return ok(bus_trip_public(trip), 200)


@bp.post("/bus-trips/<bus_trip_id>/clear-incident")
def clear_incident(bus_trip_id):
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    trip = get_bus_trip(bus_trip_id)

    if trip["status"] != "INCIDENT_HOLD":
        raise err(ERR_INVALID_STATE, "clear-incident requires INCIDENT_HOLD")

    trip["status"] = "IN_TRANSIT"
    touch(trip)
    route = DB.routes.get(trip["route_id"])
    if route:
        touch(route)
    return ok(bus_trip_public(trip), 200)


@bp.post("/bus-trips/<bus_trip_id>/complete")
def complete_trip(bus_trip_id):
    p = authenticate()
    require_role(p, {"Driver"})
    trip = get_bus_trip(bus_trip_id)
    _require_trip_driver(p, trip)

    if trip["status"] != "IN_TRANSIT":
        raise err(ERR_INVALID_STATE, "complete requires IN_TRANSIT")
    final_seq = route_final_sequence(trip["route_id"])
    if trip["current_stop_sequence"] != final_seq:
        raise err(ERR_INVALID_STATE, "complete requires being at the final stop")
    if onboard_count(trip["id"]) != 0:
        raise err(ERR_RIDERS_STILL_ONBOARD, "riders are still onboard")

    trip["status"] = "COMPLETED"
    touch(trip)
    _free_driver(trip)
    return ok(bus_trip_public(trip), 200)


@bp.post("/bus-trips/<bus_trip_id>/cancel")
def cancel_trip(bus_trip_id):
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    trip = get_bus_trip(bus_trip_id)

    if trip["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "cancel requires SCHEDULED")

    trip["status"] = "CANCELLED"
    touch(trip)
    _free_driver(trip)
    return ok(bus_trip_public(trip), 200)


def _free_driver(trip):
    """Return the driver to AVAILABLE if it was ON_DUTY for this trip."""
    driver_id = trip.get("_on_duty_driver")
    if not driver_id:
        return
    driver = DB.drivers.get(driver_id)
    if driver and driver["status"] == "ON_DUTY":
        driver["status"] = "AVAILABLE"
        touch(driver)
    trip["_on_duty_driver"] = None
