"""Route endpoints: create/list/get, posture changes, driver-assignment create.

(PRD §3.1, §3.5, §3.8, §2.10)
"""

from flask import Blueprint, request

from db import DB
from middleware import authenticate, require_role
from response import ok, ok_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVALID_REFERENCE, ERR_STALE_VERSION,
    ERR_INVALID_STATE, ERR_TRIP_IN_FLIGHT, ERR_SUBSTITUTE_RULE,
)
from services import validate as v
from services.common import (
    stamp_create, touch, parse_pagination, sorted_by_creation, paginate,
)
from services.domain import route_public, assignment_public
from services.lookup import get_route, get_district, get_driver, get_assignment

bp = Blueprint("routes", __name__)


# ---- Route CRUD --------------------------------------------------------------

@bp.post("/routes")
def create_route():
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    body = v.get_body()

    district_id = v.require_str(body, "district_id")
    name = v.require_str(body, "name")
    seat_capacity = v.require_int(body, "seat_capacity")
    if seat_capacity <= 0:
        raise err(ERR_INVALID_REQUEST, "seat_capacity must be > 0")
    wheelchair_capacity = v.optional_int(body, "wheelchair_capacity", 0)
    if wheelchair_capacity < 0:
        raise err(ERR_INVALID_REQUEST, "wheelchair_capacity must be >= 0")

    # Body FK resolution (ERR_INVALID_REFERENCE).
    if district_id not in DB.districts:
        raise err(ERR_INVALID_REFERENCE, "district_id does not resolve")

    rec = {
        "district_id": district_id,
        "name": name,
        "seat_capacity": seat_capacity,
        "wheelchair_capacity": wheelchair_capacity,
        "posture": "OPEN",
    }
    stamp_create(rec)
    DB.routes[rec["id"]] = rec
    return ok(route_public(rec), 201)


@bp.get("/routes")
def list_routes():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent", "Driver"})
    limit, offset = parse_pagination(request.args)

    district_id = request.args.get("district_id")
    posture = request.args.get("posture")

    records = list(DB.routes.values())
    if district_id is not None:
        records = [r for r in records if r["district_id"] == district_id]
    if posture is not None:
        records = [r for r in records if r["posture"] == posture]

    records = sorted_by_creation(records)
    page, total = paginate(records, limit, offset)
    return ok_list([route_public(r) for r in page], limit, offset, total)


@bp.get("/routes/<route_id>")
def get_route_ep(route_id):
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent", "Driver"})
    rec = get_route(route_id)
    return ok(route_public(rec), 200)


# ---- Posture change ----------------------------------------------------------

@bp.post("/routes/<route_id>/posture")
def change_posture(route_id):
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    rec = get_route(route_id)
    body = v.get_body()

    action = v.require_enum(body, "action", {"RESTRICT", "REOPEN", "SUSPEND"})
    expected = v.require_int(body, "expected_route_version")

    # OCC check (priority 7) precedes state-legality (priority 8).
    if expected != rec["version"]:
        raise err(ERR_STALE_VERSION, "expected_route_version does not match")

    cur = rec["posture"]

    if action == "RESTRICT":
        if cur != "OPEN":
            raise err(ERR_INVALID_STATE, "RESTRICT requires posture OPEN")
        rec["posture"] = "RESTRICTED"
        touch(rec)

    elif action == "REOPEN":
        if cur not in ("RESTRICTED", "SUSPENDED"):
            raise err(ERR_INVALID_STATE, "REOPEN requires posture RESTRICTED or SUSPENDED")
        rec["posture"] = "OPEN"
        touch(rec)

    elif action == "SUSPEND":
        if cur not in ("OPEN", "RESTRICTED"):
            raise err(ERR_INVALID_STATE, "SUSPEND requires posture OPEN or RESTRICTED")
        # Safety gate (priority 9) — after state legality.
        for t in DB.bus_trips.values():
            if t["route_id"] == route_id and t["status"] in ("BOARDING", "IN_TRANSIT"):
                raise err(ERR_TRIP_IN_FLIGHT, "A bus trip is in flight")
        rec["posture"] = "SUSPENDED"
        touch(rec)
        _suspend_cascade(route_id)

    return ok(route_public(rec), 200)


def _suspend_cascade(route_id):
    """Cascade: every SCHEDULED BusTrip -> CANCELLED; free ON_DUTY drivers."""
    for t in DB.bus_trips.values():
        if t["route_id"] == route_id and t["status"] == "SCHEDULED":
            t["status"] = "CANCELLED"
            touch(t)
            _free_driver_if_on_duty(t)


def _free_driver_if_on_duty(trip):
    """Return the driver to AVAILABLE if it was ON_DUTY for this trip."""
    driver_id = trip.get("_on_duty_driver")
    if not driver_id:
        return
    driver = DB.drivers.get(driver_id)
    if driver and driver["status"] == "ON_DUTY":
        driver["status"] = "AVAILABLE"
        touch(driver)
    trip["_on_duty_driver"] = None


# ---- DriverAssignment creation (version-guarded, PRD §3.5) -------------------

@bp.post("/routes/<route_id>/driver-assignments")
def create_assignment(route_id):
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    route = get_route(route_id)
    body = v.get_body()

    driver_id = v.require_str(body, "driver_id")
    role = body.get("role", "PRIMARY")
    if role is None:
        role = "PRIMARY"
    if role not in ("PRIMARY", "SUBSTITUTE"):
        raise err(ERR_INVALID_REQUEST, "role must be PRIMARY or SUBSTITUTE")
    replaces_assignment_id = body.get("replaces_assignment_id")
    expected = v.require_int(body, "expected_route_version")

    # Body FK resolution (ERR_INVALID_REFERENCE) — priority 5.
    driver = DB.drivers.get(driver_id)
    if driver is None:
        raise err(ERR_INVALID_REFERENCE, "driver_id does not resolve")

    # OCC check — priority 7.
    if expected != route["version"]:
        raise err(ERR_STALE_VERSION, "expected_route_version does not match")

    # Substitute rules — priority 11 (ERR_SUBSTITUTE_RULE).
    if role == "SUBSTITUTE":
        if not replaces_assignment_id:
            raise err(ERR_SUBSTITUTE_RULE, "SUBSTITUTE requires replaces_assignment_id")
        replaced = DB.driver_assignments.get(replaces_assignment_id)
        if (replaced is None
                or replaced["route_id"] != route_id
                or replaced["status"] != "ACTIVE"
                or replaced["role"] != "PRIMARY"):
            raise err(ERR_SUBSTITUTE_RULE,
                      "replaces_assignment_id must name an ACTIVE PRIMARY on the same route")
    else:  # PRIMARY
        if driver.get("is_substitute"):
            raise err(ERR_SUBSTITUTE_RULE, "substitute-only driver may not hold PRIMARY")

    rec = {
        "route_id": route_id,
        "driver_id": driver_id,
        "role": role,
        "replaces_assignment_id": replaces_assignment_id if role == "SUBSTITUTE" else None,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    DB.driver_assignments[rec["id"]] = rec

    # Side effect: SUBSTITUTE supersedes the named PRIMARY.
    if role == "SUBSTITUTE":
        replaced = DB.driver_assignments[replaces_assignment_id]
        replaced["status"] = "SUPERSEDED"
        touch(replaced)

    # Creating an assignment increments the route version by 1.
    touch(route)

    return ok(assignment_public(rec), 201)
