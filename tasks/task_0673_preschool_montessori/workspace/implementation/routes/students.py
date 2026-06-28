"""Student endpoints (PRD §3.1, SCAFFOLD §1.5)."""
from flask import Blueprint

import errors
from db import db, new_common_fields, parse_iso
from middleware import get_auth, require_role
from response import object_response, array_response
from services.common import (
    get_json_body, require_fields, require_non_empty_string, parse_pagination,
    sort_created_asc, paginate, serialize, serialize_list, str_arg,
)

bp = Blueprint("students", __name__)

READ_ROLES = {"Registrar", "Guide", "ComplianceOfficer", "Parent"}


@bp.route("/students", methods=["POST"])
def create_student():
    _, role = get_auth()
    require_role(role, {"Parent", "Registrar"})
    body = get_json_body()
    require_fields(body, ["parent_user_id", "full_name", "date_of_birth"])

    parent_user_id = require_non_empty_string(body, "parent_user_id")
    full_name = require_non_empty_string(body, "full_name")
    dob = body.get("date_of_birth")
    if not isinstance(dob, str):
        raise errors.invalid_request("date_of_birth must be an ISO 8601 string.")
    try:
        parse_iso(dob)
    except (ValueError, TypeError):
        raise errors.invalid_request("date_of_birth must be a valid ISO 8601 instant.")

    sibling_id = body.get("sibling_of_student_id")
    if sibling_id is not None:
        if not isinstance(sibling_id, str):
            raise errors.invalid_request("sibling_of_student_id must be a string.")
        # Body FK existence check (PRD §2.9).
        if sibling_id not in db.students:
            raise errors.not_found("sibling_of_student_id does not exist.")

    staff_child = False
    if "staff_child" in body and body["staff_child"] is not None:
        if not isinstance(body["staff_child"], bool):
            raise errors.invalid_request("staff_child must be a boolean.")
        staff_child = body["staff_child"]

    student = new_common_fields()
    student.update({
        "parent_user_id": parent_user_id,
        "full_name": full_name,
        "date_of_birth": dob,
        "sibling_of_student_id": sibling_id,
        "staff_child": staff_child,
    })
    db.students[student["id"]] = student
    return object_response(serialize(student), 201)


@bp.route("/students/<student_id>", methods=["GET"])
def get_student(student_id):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    student = db.students.get(student_id)
    if student is None:
        raise errors.not_found("Student not found.")
    return object_response(serialize(student), 200)


@bp.route("/students", methods=["GET"])
def list_students():
    _, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    parent_user_id = str_arg("parent_user_id")
    sibling_of = str_arg("sibling_of_student_id")

    records = list(db.students.values())
    if parent_user_id is not None:
        records = [s for s in records if s["parent_user_id"] == parent_user_id]
    if sibling_of is not None:
        records = [s for s in records if s.get("sibling_of_student_id") == sibling_of]
    records = sort_created_asc(records)
    page, total = paginate(records, limit, offset)
    return array_response(serialize_list(page), limit, offset, total)
