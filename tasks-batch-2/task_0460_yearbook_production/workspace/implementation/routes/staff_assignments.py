"""StaffAssignment routes: create, get, list, release."""
from flask import Blueprint, request

from clock import clock
from db import db, stamp_create, touch, sorted_by_created
from middleware import authenticate, authorize
from validators import (
    get_json_body, require, as_str, as_enum, as_datetime, parse_pagination,
)
from lookups import get_assignment_path, get_ref
from response import success_object, success_array
import serializers as ser
from errors import ApiError, ERR_INVALID_STATE, ERR_DEADLINE_IN_PAST

bp = Blueprint("staff_assignments", __name__)

ROLE_TITLES = {"EDITOR", "PHOTOGRAPHER", "SECTION_LEAD", "SIGNATURE_COORDINATOR"}


@bp.route("/yearbooks/staff-assignments", methods=["POST"])
def create_assignment():
    _, role = authenticate()
    authorize(role, {"Adviser"})
    body = get_json_body()

    yearbook_id = as_str(require(body, "yearbook_id"), "yearbook_id")
    get_ref(db.yearbooks, yearbook_id)
    staff_user_id = as_str(require(body, "staff_user_id"), "staff_user_id")
    role_title = as_enum(require(body, "role_title"), "role_title", ROLE_TITLES)
    deadline = as_datetime(require(body, "deadline_iso"), "deadline_iso")

    # deadline in past relative to logical clock -> 409
    if deadline < clock.now():
        raise ApiError(ERR_DEADLINE_IN_PAST, 409, "deadline_iso is in the past")

    assignment = {
        "yearbook_id": yearbook_id,
        "staff_user_id": staff_user_id,
        "role_title": role_title,
        "deadline_iso": body["deadline_iso"],
        "assigned_page_count": 0,
        "status": "ACTIVE",
    }
    stamp_create(assignment)
    db.staff_assignments[assignment["id"]] = assignment
    return success_object(ser.staff_assignment(assignment), 201)


@bp.route("/yearbooks/staff-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    _, role = authenticate()
    authorize(role, {"Adviser", "Staff"})
    assignment = get_assignment_path(assignment_id)
    return success_object(ser.staff_assignment(assignment), 200)


@bp.route("/yearbooks/staff-assignments", methods=["GET"])
def list_assignments():
    _, role = authenticate()
    authorize(role, {"Adviser", "Staff"})
    limit, offset = parse_pagination()
    yearbook_id = request.args.get("yearbook_id")
    records = list(db.staff_assignments.values())
    if yearbook_id is not None:
        records = [r for r in records if r["yearbook_id"] == yearbook_id]
    records = sorted_by_created(records)
    total = len(records)
    page = records[offset:offset + limit]
    return success_array([ser.staff_assignment(r) for r in page], limit, offset, total, 200)


@bp.route("/yearbooks/staff-assignments/<assignment_id>/release", methods=["POST"])
def release_assignment(assignment_id):
    _, role = authenticate()
    authorize(role, {"Adviser"})
    assignment = get_assignment_path(assignment_id)
    if assignment["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "assignment is not active")
    assignment["status"] = "RELEASED"
    touch(assignment)
    return success_object(ser.staff_assignment(assignment), 200)
