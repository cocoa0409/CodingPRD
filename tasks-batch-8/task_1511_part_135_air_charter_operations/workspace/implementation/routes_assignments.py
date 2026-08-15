"""AircraftAssignment and CrewAssignment endpoints."""

from flask import Blueprint, request

from httpkit import (
    ALL_ROLES, authenticate, ensure_empty_body, err, get_body, paginate,
    require_roles, respond_object, sorted_items,
)
from serializers import aircraft_assignment_json, crew_assignment_json
from services import (
    closed_intersects, compute_occupied_window, get_aircraft_or_404,
    get_assignment_or_404, get_crew_assignment_or_404, get_crew_member_or_404,
    get_trip_or_404, half_open_intersects, new_common, raw_flight_interval,
    run_crew_duty_legality, release_assignment, touch,
)
from store import db

bp = Blueprint("assignments", __name__)


# ---------------------------------------------------------------------------
# AircraftAssignment
# ---------------------------------------------------------------------------

@bp.post("/charter/aircraft-assignments")
def create_aircraft_assignment():
    authenticate()
    require_roles("DispatchManager")
    data = get_body([
        {"name": "trip_request_id", "type": "string", "required": True},
        {"name": "aircraft_id", "type": "string", "required": True},
        {"name": "expected_trip_request_version", "type": "integer",
         "required": True},
    ])
    t = get_trip_or_404(data["trip_request_id"])
    get_aircraft_or_404(data["aircraft_id"])
    # OCC is evaluated before the state preconditions (PRD section 2.11).
    if data["expected_trip_request_version"] != t["version"]:
        raise err("ERR_STALE_VERSION", 412,
                  "expected_trip_request_version does not match the trip's "
                  "current version")
    if t["status"] not in ("QUOTED", "BOOKED"):
        raise err("ERR_INVALID_STATE", 409,
                  "Assignments may only be created on QUOTED or BOOKED trips")

    # Creating an assignment supersedes any prior TENTATIVE one on the trip.
    for a in db.aircraft_assignments.values():
        if a["trip_request_id"] == t["id"] and a["status"] == "TENTATIVE":
            release_assignment(a)

    start, end = compute_occupied_window(t)
    a = new_common()
    a.update({
        "trip_request_id": t["id"],
        "aircraft_id": data["aircraft_id"],
        "status": "TENTATIVE",
        "occupied_start_at": start,
        "occupied_end_at": end,
    })
    db.aircraft_assignments[a["id"]] = a
    touch(t)
    return respond_object(aircraft_assignment_json(a), 201)


@bp.get("/charter/aircraft-assignments")
def list_aircraft_assignments():
    authenticate()
    require_roles(*ALL_ROLES)
    items = sorted_items(db.aircraft_assignments.values())
    flt_trip = request.args.get("trip_request_id")
    if flt_trip is not None:
        items = [a for a in items if a["trip_request_id"] == flt_trip]
    flt_aircraft = request.args.get("aircraft_id")
    if flt_aircraft is not None:
        items = [a for a in items if a["aircraft_id"] == flt_aircraft]
    flt_status = request.args.get("status")
    if flt_status is not None:
        items = [a for a in items if a["status"] == flt_status]
    return paginate([aircraft_assignment_json(a) for a in items])


@bp.get("/charter/aircraft-assignments/<assignment_id>")
def get_aircraft_assignment(assignment_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(aircraft_assignment_json(
        get_assignment_or_404(assignment_id)))


@bp.post("/charter/aircraft-assignments/<assignment_id>/confirm")
def confirm_aircraft_assignment(assignment_id):
    authenticate()
    require_roles("DispatchManager")
    ensure_empty_body()
    a = get_assignment_or_404(assignment_id)
    if a["status"] != "TENTATIVE":
        raise err("ERR_ASSIGNMENT_NOT_TENTATIVE", 409,
                  "Confirm requires the assignment to be TENTATIVE")
    t = db.trips[a["trip_request_id"]]
    if t["status"] != "BOOKED":
        raise err("ERR_TRIP_NOT_BOOKED", 409,
                  "Confirm requires the trip to be in BOOKED")
    aircraft = db.aircraft[a["aircraft_id"]]
    if aircraft["status"] != "AVAILABLE":
        raise err("ERR_AIRCRAFT_NOT_AVAILABLE", 409,
                  "Confirm requires the aircraft to be AVAILABLE")
    if not aircraft["on_ops_spec"]:
        raise err("ERR_AIRCRAFT_NOT_ON_OPS_SPEC", 422,
                  "The tail is not listed on the operator's FAA operations "
                  "specifications")

    # Buffered half-open occupancy vs other CONFIRMED assignments on the tail.
    for other in db.aircraft_assignments.values():
        if other["id"] == a["id"] or other["aircraft_id"] != a["aircraft_id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        if half_open_intersects(a["occupied_start_at"], a["occupied_end_at"],
                                other["occupied_start_at"], other["occupied_end_at"]):
            raise err("ERR_AIRCRAFT_SCHEDULE_CONFLICT", 409,
                      "The buffered occupied interval intersects another "
                      "CONFIRMED assignment on this aircraft")

    # Raw closed flight interval vs PLANNED/ACTIVE maintenance windows
    # (touching endpoints count as intersection).
    fs, fe = raw_flight_interval(t)
    for w in db.maintenance_windows.values():
        if w["aircraft_id"] != a["aircraft_id"]:
            continue
        if w["status"] not in ("PLANNED", "ACTIVE"):
            continue
        if closed_intersects(fs, fe, w["starts_at"], w["ends_at"]):
            raise err("ERR_MAINTENANCE_CONFLICT", 409,
                      "The flight interval intersects a PLANNED or ACTIVE "
                      "maintenance window on this aircraft")

    if aircraft["category"] != t["requested_category"]:
        raise err("ERR_CATEGORY_MISMATCH", 422,
                  "The aircraft category differs from the requested_category")

    a["status"] = "CONFIRMED"
    touch(a)
    return respond_object(aircraft_assignment_json(a))


@bp.post("/charter/aircraft-assignments/<assignment_id>/release")
def release_aircraft_assignment(assignment_id):
    authenticate()
    require_roles("DispatchManager")
    ensure_empty_body()
    a = get_assignment_or_404(assignment_id)
    if a["status"] not in ("TENTATIVE", "CONFIRMED"):
        raise err("ERR_ASSIGNMENT_ALREADY_RELEASED", 409,
                  "Release requires a TENTATIVE or CONFIRMED assignment")
    release_assignment(a)
    return respond_object(aircraft_assignment_json(a))


# ---------------------------------------------------------------------------
# CrewAssignment
# ---------------------------------------------------------------------------

@bp.post("/charter/crew-assignments")
def create_crew_assignment():
    authenticate()
    require_roles("DispatchManager")
    data = get_body([
        {"name": "trip_request_id", "type": "string", "required": True},
        {"name": "crew_member_id", "type": "string", "required": True},
        {"name": "duty_role", "type": "enum", "values": ["PIC", "SIC"],
         "required": True},
    ])
    t = get_trip_or_404(data["trip_request_id"])
    member = get_crew_member_or_404(data["crew_member_id"])
    if t["status"] not in ("QUOTED", "BOOKED"):
        raise err("ERR_INVALID_STATE", 409,
                  "Crew may only be assigned to QUOTED or BOOKED trips")
    if member["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409,
                  "Crew member must be ACTIVE to be assigned")
    if t["requested_category"] not in member["qualified_categories"]:
        raise err("ERR_CREW_NOT_TYPE_QUALIFIED", 422,
                  "The crew member is not type-qualified for the requested "
                  "category")
    c = new_common()
    c.update({
        "trip_request_id": t["id"],
        "crew_member_id": member["id"],
        "duty_role": data["duty_role"],
        "status": "PROPOSED",
        "planned_duty_minutes": None,
        "duty_legal": None,
        "rest_legal": None,
        "vetted_at": None,
    })
    db.crew_assignments[c["id"]] = c
    return respond_object(crew_assignment_json(c), 201)


@bp.get("/charter/crew-assignments")
def list_crew_assignments():
    authenticate()
    require_roles(*ALL_ROLES)
    items = sorted_items(db.crew_assignments.values())
    flt_trip = request.args.get("trip_request_id")
    if flt_trip is not None:
        items = [c for c in items if c["trip_request_id"] == flt_trip]
    flt_crew = request.args.get("crew_member_id")
    if flt_crew is not None:
        items = [c for c in items if c["crew_member_id"] == flt_crew]
    flt_status = request.args.get("status")
    if flt_status is not None:
        items = [c for c in items if c["status"] == flt_status]
    return paginate([crew_assignment_json(c) for c in items])


@bp.get("/charter/crew-assignments/<crew_assignment_id>")
def get_crew_assignment(crew_assignment_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(crew_assignment_json(
        get_crew_assignment_or_404(crew_assignment_id)))


@bp.post("/charter/crew-assignments/<crew_assignment_id>/vet")
def vet_crew_assignment(crew_assignment_id):
    authenticate()
    require_roles("DispatchManager")
    ensure_empty_body()
    c = get_crew_assignment_or_404(crew_assignment_id)
    if c["status"] != "PROPOSED":
        raise err("ERR_CREW_ASSIGNMENT_NOT_PROPOSED", 409,
                  "Vetting requires the crew assignment to be PROPOSED")
    member = db.crew_members.get(c["crew_member_id"])
    if member is None or member["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409,
                  "Vetting requires the crew member to be ACTIVE")
    planned, duty_legal, rest_legal = run_crew_duty_legality(c)
    c["planned_duty_minutes"] = planned
    c["duty_legal"] = duty_legal
    c["rest_legal"] = rest_legal
    c["vetted_at"] = db.now()
    c["status"] = "VETTED" if (duty_legal and rest_legal) else "FLAGGED_ILLEGAL"
    touch(c)
    return respond_object(crew_assignment_json(c))
