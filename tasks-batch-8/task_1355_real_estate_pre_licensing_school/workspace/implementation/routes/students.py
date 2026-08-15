"""Student endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import require_roles, get_json_body, parse_pagination, check_student_scope
from response import success_object, success_list

bp = Blueprint("students", __name__)


def _student_to_json(s):
    return {k: v for k, v in s.items()}


@bp.route("/students", methods=["POST"])
@require_roles("Registrar")
def create_student():
    body = get_json_body(
        required_fields=["school_id", "full_name", "email", "license_goal_state"],
    )
    auth = request.auth

    school = db.schools.get(body["school_id"])
    if not school:
        errors.raise_error(errors.ERR_SCHOOL_NOT_FOUND, f"School {body['school_id']} not found")

    # Uniqueness: email within school (case-insensitive)
    email_lower = body["email"].lower()
    for s in db.students.values():
        if s["school_id"] == body["school_id"] and s["email"].lower() == email_lower:
            errors.raise_error(errors.ERR_DUPLICATE_STUDENT_EMAIL,
                               "Email already registered in this school")

    student = db.new_entity({
        "school_id": body["school_id"],
        "full_name": body["full_name"],
        "email": body["email"],
        "license_goal_state": body["license_goal_state"],
    })
    db.students[student["id"]] = student
    db.audit("Student", student["id"], "STUDENT_CREATED", auth["role"], auth["user_id"])
    return success_object(_student_to_json(student), 201)


@bp.route("/students", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def list_students():
    limit, offset = parse_pagination()
    items = list(db.students.values())

    school_id = request.args.get("school_id")
    if school_id:
        items = [s for s in items if s["school_id"] == school_id]

    email = request.args.get("email")
    if email:
        items = [s for s in items if s["email"].lower() == email.lower()]

    auth = request.auth
    if auth["role"] == "SchoolDirector":
        own_school_ids = {s["id"] for s in db.schools.values() if s.get("director_user_id") == auth["user_id"]}
        items = [s for s in items if s["school_id"] in own_school_ids]

    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_student_to_json(s) for s in page], limit, offset, total)


@bp.route("/students/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Student")
def get_student(id):
    student = db.students.get(id)
    if not student:
        errors.raise_error(errors.ERR_STUDENT_NOT_FOUND, f"Student {id} not found")
    auth = request.auth
    check_student_scope(id, auth)
    if auth["role"] == "SchoolDirector":
        school = db.schools.get(student["school_id"])
        if school and school.get("director_user_id") != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Director does not own this school")
    return success_object(_student_to_json(student))
