"""Student routes (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import validate
from services.listing import paginate_and_render
from services.serialize import student_view

bp = Blueprint("students", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


@bp.route("/institutions/students", methods=["POST"])
def create_student():
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    body = validate.get_body()

    institution_id = validate.require_string(body, "institution_id")
    institution = db.institutions.get(institution_id)
    if institution is None:
        raise err("ERR_NOT_FOUND", "Institution not found")

    external_ref = validate.require_string(body, "external_ref")
    full_name = validate.require_string(body, "full_name")
    email = validate.require_string(body, "email")

    # external_ref unique per institution (PRD §3.2).
    for s in db.students.values():
        if s["institution_id"] == institution_id and s["external_ref"] == external_ref:
            raise err("ERR_INVALID_REQUEST", "external_ref already in use")

    record = db.stamp_new({
        "institution_id": institution_id,
        "external_ref": external_ref,
        "full_name": full_name,
        "email": email,
        "has_active_hold": False,
    })
    db.students[record["id"]] = record
    return success(student_view(record), status=201)


@bp.route("/institutions/students/<student_id>", methods=["GET"])
def get_student(student_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.students.get(student_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Student not found")
    return success(student_view(record), status=200)


@bp.route("/institutions/students", methods=["GET"])
def list_students():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    institution_id = request.args.get("institution_id")
    records = list(db.students.values())
    if institution_id is not None:
        records = [r for r in records if r["institution_id"] == institution_id]
    return paginate_and_render(records, student_view)
