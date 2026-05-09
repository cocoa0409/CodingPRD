"""Instructor + Student registration."""
from flask import Blueprint, request

from db import bump, make_common_fields, store
from errors import raise_api
from middleware import require_roles
from response import success
from services.lookup import get_instructor
from services.occ import check_version

instructors_bp = Blueprint("instructors", __name__)


def _validate_windows(windows):
    if windows is None:
        return []
    if not isinstance(windows, list):
        raise_api("ERR_INVALID_PRICING", "availability_windows must be a list")
    out = []
    for w in windows:
        if not isinstance(w, dict):
            raise_api("ERR_INVALID_PRICING", "window must be an object")
        try:
            s = int(w.get("start_ts"))
            e = int(w.get("end_ts"))
        except (TypeError, ValueError):
            raise_api("ERR_INVALID_PRICING", "start_ts/end_ts required")
        if e < s:
            raise_api("ERR_INVALID_PRICING", "end_ts must be >= start_ts")
        out.append({"start_ts": s, "end_ts": e})
    return out


@instructors_bp.route("/instructors", methods=["POST"])
def register_instructor():
    require_roles("AcademicAdmin")
    body = request.get_json(silent=True) or {}
    name = body.get("display_name")
    email = body.get("email")
    bio = body.get("bio", "")
    if not name:
        raise_api("ERR_INVALID_PRICING", "display_name required")
    if not email:
        raise_api("ERR_INVALID_PRICING", "email required")
    # unique email
    for ins in store.instructors.values():
        if ins["email"] == email:
            raise_api("ERR_INVALID_PRICING", "instructor email already exists")
    windows = _validate_windows(body.get("availability_windows", []))
    instructor = {
        **make_common_fields(),
        "display_name": name,
        "email": email,
        "bio": bio,
        "availability_windows": windows,
    }
    store.instructors[instructor["id"]] = instructor
    return success(instructor, http_status=201)


@instructors_bp.route("/instructors/<instructor_id>", methods=["GET"])
def get_one_instructor(instructor_id):
    require_roles("Instructor", "TeachingAssistant", "Student", "AcademicAdmin")
    instructor = get_instructor(instructor_id)
    return success(dict(instructor))


@instructors_bp.route("/instructors/<instructor_id>/availability", methods=["PATCH"])
def update_availability(instructor_id):
    user_id, role = require_roles("Instructor", "AcademicAdmin")
    instructor = get_instructor(instructor_id)
    if role == "Instructor" and instructor["id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the instructor")
    body = request.get_json(silent=True) or {}
    check_version(instructor, body)
    windows = _validate_windows(body.get("availability_windows", []))
    instructor["availability_windows"] = windows
    bump(instructor)
    return success(dict(instructor))


@instructors_bp.route("/students", methods=["POST"])
def register_student():
    require_roles("AcademicAdmin", "Student")
    body = request.get_json(silent=True) or {}
    name = body.get("display_name")
    email = body.get("email")
    if not name:
        raise_api("ERR_INVALID_PRICING", "display_name required")
    if not email:
        raise_api("ERR_INVALID_PRICING", "email required")
    for s in store.students.values():
        if s["email"] == email:
            raise_api("ERR_INVALID_PRICING", "student email already exists")
    student = {
        **make_common_fields(),
        "display_name": name,
        "email": email,
    }
    store.students[student["id"]] = student
    return success(student, http_status=201)
