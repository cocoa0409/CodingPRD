"""CrewMember endpoints."""
from flask import Blueprint, request

from db import db
from errors import validation, ApiError, ERR_CREW_INVALID_STATE, ERR_INSUFFICIENT_TRAINING
from middleware import require_roles, require_read
from response import success_object, success_list
from serializers import crew_view
from services.core import (
    make_record, touch, require_exists, get_pagination, paginate,
    duty_window_sums, flight_hours_total,
)
from util import parse_date

bp = Blueprint("crew", __name__)

CREW_ROLES = {"CAPTAIN", "FIRST_OFFICER"}
MIN_TRAINING_HOURS = 25


def _view(rec):
    sum7, sum28 = duty_window_sums(rec["id"])
    return crew_view(
        rec,
        duty_7d=float(sum7),
        duty_28d=float(sum28),
        flight_total=flight_hours_total(rec["id"]),
    )


@bp.route("/crew", methods=["POST"])
def hire_crew():
    require_roles("FlightOpsManager")
    body = request.get_json(silent=True) or {}

    aircraft_id = body.get("aircraft_id")
    if aircraft_id is not None:
        require_exists(db.aircraft, aircraft_id, "aircraft_id does not resolve")
    if not isinstance(aircraft_id, str) or not aircraft_id:
        raise validation("aircraft_id is required")

    full_name = body.get("full_name")
    if not isinstance(full_name, str) or not full_name:
        raise validation("full_name is required")
    crew_role = body.get("crew_role")
    if crew_role not in CREW_ROLES:
        raise validation("crew_role must be CAPTAIN or FIRST_OFFICER")
    hire_date = body.get("hire_date")
    parse_date(hire_date, "hire_date")

    rec = make_record({
        "aircraft_id": aircraft_id,
        "full_name": full_name,
        "crew_role": crew_role,
        "hire_date": hire_date,
        "status": "HIRED",
        "training_hours_accumulated": 0.0,
    })
    db.crew[rec["id"]] = rec
    return success_object(_view(rec), 201)


@bp.route("/crew/<crew_id>", methods=["GET"])
def get_crew(crew_id):
    require_read()
    rec = require_exists(db.crew, crew_id)
    return success_object(_view(rec))


@bp.route("/aircraft/<aircraft_id>/crew", methods=["GET"])
def list_crew(aircraft_id):
    require_read()
    require_exists(db.aircraft, aircraft_id)
    limit, offset = get_pagination(request.args)
    records = [c for c in db.crew.values() if c["aircraft_id"] == aircraft_id]
    page, total = paginate(records, limit, offset)
    return success_list([_view(r) for r in page], limit, offset, total)


@bp.route("/crew/<crew_id>/begin-training", methods=["POST"])
def begin_training(crew_id):
    require_roles("FlightOpsManager")
    rec = require_exists(db.crew, crew_id)
    if rec["status"] != "HIRED":
        raise ApiError(ERR_CREW_INVALID_STATE, "CrewMember must be in HIRED", 409)
    rec["status"] = "IN_TRAINING"
    touch(rec, bump_version=True)
    return success_object(_view(rec))


@bp.route("/crew/<crew_id>/complete-training", methods=["POST"])
def complete_training(crew_id):
    require_roles("FlightOpsManager")
    rec = require_exists(db.crew, crew_id)
    body = request.get_json(silent=True) or {}

    if rec["status"] != "IN_TRAINING":
        raise ApiError(ERR_CREW_INVALID_STATE, "CrewMember must be in IN_TRAINING", 409)

    training_hours = body.get("training_hours")
    check_ride_passed = body.get("check_ride_passed")
    if isinstance(training_hours, bool) or not isinstance(training_hours, (int, float)):
        raise validation("training_hours is required and must be a number")
    if not isinstance(check_ride_passed, bool):
        raise validation("check_ride_passed is required and must be a boolean")

    if training_hours < MIN_TRAINING_HOURS or check_ride_passed is not True:
        raise ApiError(ERR_INSUFFICIENT_TRAINING,
                       "complete-training requires training_hours >= 25 and check_ride_passed == true", 422)

    rec["training_hours_accumulated"] = float(
        rec["training_hours_accumulated"] + training_hours
    )
    rec["status"] = "QUALIFIED"
    touch(rec, bump_version=True)
    return success_object(_view(rec))


@bp.route("/crew/<crew_id>/deactivate", methods=["POST"])
def deactivate(crew_id):
    require_roles("FlightOpsManager")
    rec = require_exists(db.crew, crew_id)
    if rec["status"] not in ("HIRED", "IN_TRAINING", "QUALIFIED"):
        raise ApiError(ERR_CREW_INVALID_STATE,
                       "CrewMember must be in HIRED, IN_TRAINING, or QUALIFIED", 409)
    # release ASSIGNED duty assignments whose trip is still open
    for a in db.assignments.values():
        if a["crew_member_id"] != crew_id or a["status"] != "ASSIGNED":
            continue
        trip = db.trips.get(a["trip_id"])
        if trip is not None and trip["status"] in ("REQUESTED", "APPROVED", "SCHEDULED"):
            a["status"] = "RELEASED"
            touch(a)
    rec["status"] = "INACTIVE"
    touch(rec, bump_version=True)
    return success_object(_view(rec))
