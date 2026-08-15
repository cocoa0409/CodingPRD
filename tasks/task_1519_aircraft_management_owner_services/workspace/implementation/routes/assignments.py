"""DutyAssignment endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    validation, ApiError,
    ERR_TRIP_INVALID_STATE, ERR_CREW_NOT_QUALIFIED, ERR_DUTY_LIMIT_EXCEEDED,
    ERR_CREW_OVERLAP, ERR_ASSIGNMENT_INVALID_STATE,
)
from middleware import require_roles, require_read
from response import success_object, success_list
from serializers import assignment_view
from services.core import (
    make_record, touch, require_exists, filter_value_exists,
    get_pagination, paginate, compute_duty_hours, duty_window_sums,
    DUTY_LIMIT_7D_HOURS, DUTY_LIMIT_28D_HOURS,
)
from util import parse_datetime

bp = Blueprint("assignments", __name__)

DUTY_ROLES = {"PIC", "SIC"}
STATUSES = {"ASSIGNED", "RELEASED", "COMPLETED"}


@bp.route("/assignments", methods=["POST"])
def create_assignment():
    require_roles("FlightOpsManager")
    body = request.get_json(silent=True) or {}

    trip_id = body.get("trip_id")
    crew_member_id = body.get("crew_member_id")
    if trip_id is not None:
        require_exists(db.trips, trip_id, "trip_id does not resolve")
    if crew_member_id is not None:
        require_exists(db.crew, crew_member_id, "crew_member_id does not resolve")

    if not isinstance(trip_id, str) or not trip_id:
        raise validation("trip_id is required")
    if not isinstance(crew_member_id, str) or not crew_member_id:
        raise validation("crew_member_id is required")

    duty_role = body.get("duty_role")
    if duty_role not in DUTY_ROLES:
        raise validation("duty_role must be PIC or SIC")

    duty_start = parse_datetime(body.get("duty_start_at"), "duty_start_at")
    duty_end = parse_datetime(body.get("duty_end_at"), "duty_end_at")
    if not duty_start < duty_end:
        raise validation("duty_start_at must be strictly earlier than duty_end_at")

    trip = db.trips[trip_id]
    member = db.crew[crew_member_id]

    # crew are dedicated to one aircraft
    if member["aircraft_id"] != trip["aircraft_id"]:
        raise validation("Crew member is not dedicated to the trip's aircraft")

    # state gate: trip must be APPROVED or SCHEDULED
    if trip["status"] not in ("APPROVED", "SCHEDULED"):
        raise ApiError(ERR_TRIP_INVALID_STATE,
                       "The referenced trip must be in APPROVED or SCHEDULED status", 409)

    # business gate 1: crew member must be QUALIFIED
    if member["status"] != "QUALIFIED":
        raise ApiError(ERR_CREW_NOT_QUALIFIED,
                       "Crew member status must be QUALIFIED", 409)

    duty_hours = compute_duty_hours(duty_start, duty_end)

    # business gate 2: projected duty limits (strictly-greater rejects; equality passes)
    sum7, sum28 = duty_window_sums(crew_member_id)
    new_hours = Decimal(str(duty_hours))
    if sum7 + new_hours > DUTY_LIMIT_7D_HOURS or sum28 + new_hours > DUTY_LIMIT_28D_HOURS:
        raise ApiError(ERR_DUTY_LIMIT_EXCEEDED,
                       "Projected 7-day or 28-day duty total strictly exceeds its limit", 422)

    # temporal gate: half-open window overlap with other ASSIGNED/COMPLETED windows
    for a in db.assignments.values():
        if a["crew_member_id"] != crew_member_id:
            continue
        if a["status"] not in ("ASSIGNED", "COMPLETED"):
            continue
        if duty_start < a["_duty_end"] and a["_duty_start"] < duty_end:
            raise ApiError(ERR_CREW_OVERLAP,
                           "New duty window has a strictly positive intersection with another duty window of the crew member", 409)

    rec = make_record({
        "trip_id": trip_id,
        "crew_member_id": crew_member_id,
        "duty_role": duty_role,
        "duty_start_at": body.get("duty_start_at"),
        "duty_end_at": body.get("duty_end_at"),
        "duty_hours": duty_hours,
        "status": "ASSIGNED",
        "_duty_start": duty_start,
        "_duty_end": duty_end,
    })
    db.assignments[rec["id"]] = rec
    return success_object(assignment_view(rec), 201)


@bp.route("/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    require_read()
    rec = require_exists(db.assignments, assignment_id)
    return success_object(assignment_view(rec))


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    require_read()
    trip_id = request.args.get("trip_id")
    crew_member_id = request.args.get("crew_member_id")
    status = request.args.get("status")
    filter_value_exists(db.trips, trip_id)
    filter_value_exists(db.crew, crew_member_id)
    if status is not None and status not in STATUSES:
        raise validation("status is not a valid enum value")

    limit, offset = get_pagination(request.args)
    records = list(db.assignments.values())
    if trip_id is not None:
        records = [r for r in records if r["trip_id"] == trip_id]
    if crew_member_id is not None:
        records = [r for r in records if r["crew_member_id"] == crew_member_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return success_list([assignment_view(r) for r in page], limit, offset, total)


@bp.route("/assignments/<assignment_id>", methods=["DELETE"])
def release_assignment(assignment_id):
    require_roles("FlightOpsManager")
    rec = require_exists(db.assignments, assignment_id)
    if rec["status"] != "ASSIGNED":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE,
                       "Assignment must be ASSIGNED to be released", 409)
    rec["status"] = "RELEASED"
    touch(rec, bump_version=True)
    return success_object(assignment_view(rec))
