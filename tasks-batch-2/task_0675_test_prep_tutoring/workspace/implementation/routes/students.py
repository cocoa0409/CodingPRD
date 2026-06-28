"""Student endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
import response
from errors import err
from middleware import require_auth, get_json_body, parse_pagination, get_identity
from services import serialize, validators
from services.listing import sort_and_page

bp = Blueprint("students", __name__)


@bp.post("/students/register")
def register_student():
    # Public anonymous self-registration: no auth headers required (PRD §2.1).
    body = get_json_body()
    email = validators.require_str(body, "email")
    full_name = validators.require_str(body, "full_name")

    # email is unique across Student (scaffold constraint). Duplicate email is a
    # body well-formedness violation -> ERR_INVALID_REQUEST.
    for s in db.students.values():
        if s["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email already registered.")

    rec = {
        "id": db.new_id(),
        "email": email,
        "full_name": full_name,
        "diagnostic_score": None,
    }
    db.stamp_create(rec)
    db.students[rec["id"]] = rec
    return response.success(serialize.student(rec), 201)


def _authorize_student_self(user_id, role, student_id):
    # A Student may act only on its own student record (PRD §2.1).
    if role == "Student" and user_id != student_id:
        raise err("ERR_UNAUTHORIZED", "Student may only access its own record.")


@bp.get("/students/<sid>")
def get_student(sid):
    user_id, role = require_auth({"Student", "Registrar"})
    student = db.students.get(sid)
    if student is None:
        raise err("ERR_NOT_FOUND", "Student not found.")
    _authorize_student_self(user_id, role, sid)
    return response.success(serialize.student(student), 200)


@bp.get("/students/<sid>/enrollments")
def list_student_enrollments(sid):
    user_id, role = require_auth({"Student", "Registrar"})
    student = db.students.get(sid)
    if student is None:
        raise err("ERR_NOT_FOUND", "Student not found.")
    _authorize_student_self(user_id, role, sid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = [e for e in db.enrollments.values() if e["student_id"] == sid]
    if status is not None:
        records = [e for e in records if e["status"] == status]
    page, total = sort_and_page(records, limit, offset)
    return response.success_list(
        [serialize.enrollment(e) for e in page], limit, offset, total
    )
