"""Crew assignment endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, require_role
from response import success_list, success_object
from serializers import serialize_crew_assignment
from services.core import (
    MAX_DUTY_HOURS,
    assignment_covers_flight,
    recompute_crew_coverage,
    stamp_new,
    touch,
)
from validators import (
    get_json_body,
    get_json_body_optional,
    opt_query_enum,
    pagination_params,
    req_datetime,
    req_string,
)

bp = Blueprint("crew", __name__)

CREW_ROLES = {"CAPTAIN", "FIRST_OFFICER", "FLIGHT_ATTENDANT"}
LEGALITY_STATUSES = {"LEGAL", "FLAGGED_ILLEGAL"}
CREW_READ_ROLES = ["CrewScheduler", "OpsController", "DutyManager"]


@bp.post("/irops/flights/<fid>/crew-assignments")
def create_assignment(fid):
    caller = authenticate()
    require_role(caller, ["CrewScheduler"])
    body = get_json_body()
    crew_member_ref = req_string(body, "crew_member_ref")
    crew_role = body.get("crew_role")
    if not isinstance(crew_role, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "crew_role must be a string")
    if crew_role not in CREW_ROLES:
        errors.raise_error(errors.ERR_INVALID_ENUM,
                           "crew_role value %r outside declared enum domain" % crew_role)
    duty_start = req_datetime(body, "duty_start_utc")
    duty_end = req_datetime(body, "duty_end_utc")
    if duty_end <= duty_start:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "duty_end_utc must be strictly after duty_start_utc")
    if duty_end > duty_start + timedelta(hours=MAX_DUTY_HOURS):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "duty window exceeds MAX_DUTY_HOURS (14h)")
    f = db.flights.get(fid)
    if f is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Flight not found")
    # half-open overlap check among ASSIGNED assignments of the same crew member
    for a in db.crew_assignments.values():
        if a["crew_member_ref"] != crew_member_ref:
            continue
        if a["assignment_status"] != "ASSIGNED":
            continue
        if duty_start < a["duty_end_utc"] and a["duty_start_utc"] < duty_end:
            errors.raise_error(errors.ERR_CREW_DUTY_OVERLAP,
                               "Duty window overlaps an existing ASSIGNED duty")
    a = stamp_new({
        "flight_id": fid,
        "crew_member_ref": crew_member_ref,
        "crew_role": crew_role,
        "duty_start_utc": duty_start,
        "duty_end_utc": duty_end,
        "legality_status": "LEGAL" if assignment_covers_flight(
            {"duty_start_utc": duty_start, "duty_end_utc": duty_end}, f) else "FLAGGED_ILLEGAL",
        "assignment_status": "ASSIGNED",
    })
    db.crew_assignments[a["id"]] = a
    recompute_crew_coverage(f)
    f["version"] += 1  # coverage recompute bumps the flight's version
    return success_object(serialize_crew_assignment(a), 201)


@bp.get("/irops/crew-assignments/<aid>")
def get_assignment(aid):
    caller = authenticate()
    require_role(caller, CREW_READ_ROLES)
    a = db.crew_assignments.get(aid)
    if a is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "CrewAssignment not found")
    return success_object(serialize_crew_assignment(a), 200)


@bp.get("/irops/crew-assignments")
def list_assignments():
    caller = authenticate()
    require_role(caller, CREW_READ_ROLES)
    flight_id = request.args.get("flight_id")
    ref = request.args.get("crew_member_ref")
    legality = opt_query_enum("legality_status", LEGALITY_STATUSES)
    limit, offset = pagination_params()
    items = sorted(db.crew_assignments.values(), key=lambda a: a["created_at"])
    if flight_id is not None:
        items = [a for a in items if a["flight_id"] == flight_id]
    if ref is not None:
        items = [a for a in items if a["crew_member_ref"] == ref]
    if legality is not None:
        items = [a for a in items if a["legality_status"] == legality]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_crew_assignment(a) for a in page], limit, offset, total)


@bp.post("/irops/crew-assignments/<aid>/release")
def release_assignment(aid):
    caller = authenticate()
    require_role(caller, ["CrewScheduler"])
    get_json_body_optional()
    a = db.crew_assignments.get(aid)
    if a is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "CrewAssignment not found")
    if a["assignment_status"] != "ASSIGNED":
        errors.raise_error(errors.ERR_INVALID_CREW_STATE,
                           "Assignment is not ASSIGNED")
    a["assignment_status"] = "RELEASED"
    touch(a)
    f = db.flights.get(a["flight_id"])
    if f is not None:
        recompute_crew_coverage(f)
        f["version"] += 1
    return success_object(serialize_crew_assignment(a), 200)
