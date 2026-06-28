"""ProgramSession routes (PRD §3.1, §3.5)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from response import success, list_success
from services import serialize
from services.common import (
    new_record, get_body, get_or_404, paginate, touch, req_str, req_int,
)
from routes.time_slots import req_dt

bp = Blueprint("program_sessions", __name__)

READ_ROLES = {"GardenAdmin", "GardenStaff", "RentalCoordinator",
              "DevelopmentOfficer", "Visitor"}


@bp.route("/v1/program-sessions", methods=["POST"])
def create_program_session():
    _, role = get_identity()
    require_role(role, {"GardenAdmin", "GardenStaff"})
    body = get_body()
    garden_id = req_str(body, "garden_id")
    title = req_str(body, "title")
    starts_at = req_dt(body, "starts_at")
    capacity = req_int(body, "capacity", min_value=1)
    tuition_cents = req_int(body, "tuition_cents", min_value=0)
    get_or_404(db.gardens, garden_id)
    rec = new_record({
        "garden_id": garden_id,
        "title": title,
        "starts_at": starts_at,
        "capacity": capacity,
        "tuition_cents": tuition_cents,
        "enrolled_count": 0,
        "status": "OPEN",
    })
    db.program_sessions[rec["id"]] = rec
    return success(serialize.program_session(rec), status=201)


@bp.route("/v1/program-sessions/<session_id>", methods=["GET"])
def read_program_session(session_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.program_sessions, session_id)
    return success(serialize.program_session(rec), status=200)


@bp.route("/v1/program-sessions", methods=["GET"])
def list_program_sessions():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    garden_id = request.args.get("garden_id")
    status = request.args.get("status")
    records = list(db.program_sessions.values())
    if garden_id is not None:
        records = [r for r in records if r["garden_id"] == garden_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.program_session(r) for r in page],
                        limit, offset, total)


@bp.route("/v1/program-sessions/<session_id>/close", methods=["POST"])
def close_program_session(session_id):
    _, role = get_identity()
    require_role(role, {"GardenAdmin", "GardenStaff"})
    rec = get_or_404(db.program_sessions, session_id)
    if rec["status"] != "OPEN":
        raise errors.invalid_state()
    rec["status"] = "CLOSED"
    touch(rec)
    return success(serialize.program_session(rec), status=200)
