"""StaffAssignment endpoints with OCC on Classroom.version (PRD §2.5, §3.10)."""
from flask import Blueprint

import errors
from db import db, new_common_fields, touch
from middleware import get_auth, require_role
from response import object_response
from services import compliance
from services.common import (
    get_json_body, require_fields, require_non_empty_string, require_int, serialize,
)

bp = Blueprint("staff_assignments", __name__)


@bp.route("/staff-assignments", methods=["POST"])
def create_staff_assignment():
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    body = get_json_body()
    require_fields(body, ["classroom_id", "staff_name", "expected_classroom_version"])

    classroom_id = body["classroom_id"]
    if not isinstance(classroom_id, str):
        raise errors.invalid_request("classroom_id must be a string.")
    staff_name = require_non_empty_string(body, "staff_name")
    expected_version = require_int(body, "expected_classroom_version")

    # Existence (priority 4) before OCC (priority 6).
    classroom = db.classrooms.get(classroom_id)
    if classroom is None:
        raise errors.not_found("classroom_id does not exist.")

    # OCC (priority 6).
    if expected_version != classroom["version"]:
        raise errors.stale_classroom_version()

    sa = new_common_fields()
    sa.update({
        "classroom_id": classroom_id,
        "staff_name": staff_name,
        "status": "ACTIVE",
        "expected_classroom_version": expected_version,
    })
    db.staff_assignments[sa["id"]] = sa

    # Bump assigned_staff_count, recompute compliance, increment classroom.version.
    compliance.recompute_and_touch(classroom)
    return object_response(serialize(sa), 201)


@bp.route("/staff-assignments/<sa_id>", methods=["GET"])
def get_staff_assignment(sa_id):
    _, role = get_auth()
    require_role(role, {"Registrar", "ComplianceOfficer"})
    sa = db.staff_assignments.get(sa_id)
    if sa is None:
        raise errors.not_found("Staff assignment not found.")
    return object_response(serialize(sa), 200)


@bp.route("/staff-assignments/<sa_id>/end", methods=["POST"])
def end_staff_assignment(sa_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    body = get_json_body()
    require_fields(body, ["expected_classroom_version"])
    expected_version = require_int(body, "expected_classroom_version")

    # Existence (priority 4).
    sa = db.staff_assignments.get(sa_id)
    if sa is None:
        raise errors.not_found("Staff assignment not found.")
    # State (priority 5): only ACTIVE assignments may be ended.
    if sa["status"] != "ACTIVE":
        raise errors.invalid_state()
    classroom = db.classrooms[sa["classroom_id"]]
    # OCC (priority 6).
    if expected_version != classroom["version"]:
        raise errors.stale_classroom_version()

    sa["status"] = "ENDED"
    touch(sa)
    compliance.recompute_and_touch(classroom)
    return object_response(serialize(sa), 200)
