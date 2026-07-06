"""Assignment top-level GET/check-in routes."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND,
                    ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE)
from response import envelope_object, envelope_array
from services import pagination
from services.serializers import shift_assignment_dto
from db import parse_iso

bp = Blueprint("assignments", __name__)


@bp.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    a = db.shift_assignments.get(aid)
    if a is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Assignment not found")
    return envelope_object(shift_assignment_dto(a), status=200)


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    limit, offset = pagination.parse_pagination()
    items = list(db.shift_assignments.values())
    for k in ("member_id", "shift_id", "status"):
        v = request.args.get(k)
        if v is not None:
            items = [x for x in items if x[k] == v]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([shift_assignment_dto(a) for a in window], limit, offset, total)


@bp.route("/assignments/<aid>/check-in", methods=["POST"])
def check_in(aid):
    user_id, _ = require_role({ROLE_MEMBER})
    a = db.shift_assignments.get(aid)
    if a is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Assignment not found")
    shift = db.project_shifts.get(a["shift_id"])
    if shift is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Shift not found")
    if a["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "Assignment.status must be CONFIRMED")
    if a["member_id"] != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must equal assignment.member_id")
    now = db.clock_dt().timestamp()
    start_ts = parse_iso(shift["shift_start_utc"]).timestamp()
    end_ts = start_ts + shift["duration_minutes"] * 60
    if now < start_ts:
        raise_err(ERR_INVALID_STATE, "logical clock has not reached shift_start_utc")
    if now >= end_ts:
        raise_err(ERR_INVALID_STATE, "logical clock has passed shift end")
    a["status"] = "CHECKED_IN"
    a["check_in_utc"] = db.get_clock_iso()
    db.touch(a)
    return envelope_object(shift_assignment_dto(a), status=200)
