"""MaintenanceProgram endpoints."""
from flask import Blueprint, request

from db import db
from errors import validation, ApiError, ERR_PROGRAM_INVALID_STATE
from middleware import require_roles, require_read
from response import success_object, success_list
from serializers import program_view
from services.core import make_record, touch, require_exists, get_pagination, paginate

bp = Blueprint("programs", __name__)


@bp.route("/programs", methods=["POST"])
def create_program():
    require_roles("MaintenancePlanner")
    body = request.get_json(silent=True) or {}

    aircraft_id = body.get("aircraft_id")
    if aircraft_id is not None:
        require_exists(db.aircraft, aircraft_id, "aircraft_id does not resolve")
    if not isinstance(aircraft_id, str) or not aircraft_id:
        raise validation("aircraft_id is required")

    program_name = body.get("program_name")
    if not isinstance(program_name, str) or not program_name:
        raise validation("program_name is required")

    rate = body.get("rate_per_hour_cents")
    if isinstance(rate, bool) or not isinstance(rate, int) or rate < 0:
        raise validation("rate_per_hour_cents must be a non-negative integer")

    rec = make_record({
        "aircraft_id": aircraft_id,
        "program_name": program_name,
        "rate_per_hour_cents": rate,
        "status": "QUOTED",
    })
    db.programs[rec["id"]] = rec
    return success_object(program_view(rec), 201)


@bp.route("/programs/<program_id>", methods=["GET"])
def get_program(program_id):
    require_read()
    rec = require_exists(db.programs, program_id)
    return success_object(program_view(rec))


@bp.route("/aircraft/<aircraft_id>/programs", methods=["GET"])
def list_programs(aircraft_id):
    require_read()
    require_exists(db.aircraft, aircraft_id)
    limit, offset = get_pagination(request.args)
    records = [p for p in db.programs.values() if p["aircraft_id"] == aircraft_id]
    page, total = paginate(records, limit, offset)
    return success_list([program_view(r) for r in page], limit, offset, total)


@bp.route("/programs/<program_id>/enroll", methods=["POST"])
def enroll_program(program_id):
    require_roles("MaintenancePlanner", "AccountExecutive")
    rec = require_exists(db.programs, program_id)
    if rec["status"] not in ("QUOTED", "SUSPENDED"):
        raise ApiError(ERR_PROGRAM_INVALID_STATE,
                       "Program must be in QUOTED or SUSPENDED", 409)
    rec["status"] = "ENROLLED"
    touch(rec, bump_version=True)
    return success_object(program_view(rec))


@bp.route("/programs/<program_id>/suspend", methods=["POST"])
def suspend_program(program_id):
    require_roles("MaintenancePlanner")
    rec = require_exists(db.programs, program_id)
    if rec["status"] != "ENROLLED":
        raise ApiError(ERR_PROGRAM_INVALID_STATE, "Program must be in ENROLLED", 409)
    rec["status"] = "SUSPENDED"
    touch(rec, bump_version=True)
    return success_object(program_view(rec))


@bp.route("/programs/<program_id>/cancel", methods=["POST"])
def cancel_program(program_id):
    require_roles("AccountExecutive")
    rec = require_exists(db.programs, program_id)
    if rec["status"] not in ("QUOTED", "ENROLLED", "SUSPENDED"):
        raise ApiError(ERR_PROGRAM_INVALID_STATE,
                       "Program must be in QUOTED, ENROLLED, or SUSPENDED", 409)
    rec["status"] = "CANCELLED"
    touch(rec, bump_version=True)
    return success_object(program_view(rec))
