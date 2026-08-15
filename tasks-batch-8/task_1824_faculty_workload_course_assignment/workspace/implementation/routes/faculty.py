"""FacultyMember endpoints: roster CRUD plus status lifecycle with the
leave/separation cascade (PRD §3.2)."""

import db
from errors import (
    ApiError,
    ERR_FACULTY_NOT_FOUND,
    ERR_DUPLICATE_FACULTY_EMAIL,
    ERR_INVALID_FACULTY_STATE,
)
from middleware import authenticate, ALL_ROLES, CHAIR
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, present, pagination_params, paginate, apply_filters
import services

bp = make_blueprint("faculty")

RANKS = ["ADJUNCT", "LECTURER", "ASSISTANT_PROFESSOR", "ASSOCIATE_PROFESSOR", "PROFESSOR"]
FACULTY_STATUSES = ["ACTIVE", "ON_LEAVE", "SEPARATED"]

# Reachable status transitions (cyclic ACTIVE <-> ON_LEAVE; SEPARATED terminal).
_ALLOWED_TRANSITIONS = {
    ("ACTIVE", "ON_LEAVE"),
    ("ON_LEAVE", "ACTIVE"),
    ("ACTIVE", "SEPARATED"),
    ("ON_LEAVE", "SEPARATED"),
}


def require_faculty(faculty_id):
    faculty = db.get("faculty_members", faculty_id)
    if faculty is None:
        raise ApiError(ERR_FACULTY_NOT_FOUND, 404, "faculty member not found")
    return faculty


@bp.post("/faculty-members")
def create_faculty():
    authenticate([CHAIR])
    body = body_json()
    check_shape(body, {
        "full_name": {"type": "string", "required": True},
        "email": {"type": "string", "required": True},
        "rank": {"type": "enum", "values": RANKS, "required": True},
        "base_salary_cents": {"type": "integer", "required": True},
        "is_union_covered": {"type": "boolean"},
        "base_load_credits": {"type": "number"},
        "preferred_course_ids": {"type": "string_array"},
    })
    for existing in db.all_of("faculty_members"):
        if existing["email"] == body["email"]:
            raise ApiError(ERR_DUPLICATE_FACULTY_EMAIL, 409, "email already exists")
    faculty = db.new_entity("faculty_members", {
        "full_name": body["full_name"],
        "email": body["email"],
        "rank": body["rank"],
        "base_salary_cents": body["base_salary_cents"],
        "is_union_covered": body["is_union_covered"] if present(body, "is_union_covered") else True,
        "base_load_credits": body["base_load_credits"] if present(body, "base_load_credits") else 12,
        "preferred_course_ids": list(body["preferred_course_ids"]) if present(body, "preferred_course_ids") else [],
        "status": "ACTIVE",
    })
    return success_obj(db.public(faculty), 201)


@bp.get("/faculty-members")
def list_faculty():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("faculty_members"), ["status", "rank"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(f) for f in page], limit, offset, total, has_more)


@bp.get("/faculty-members/<facultyId>")
def get_faculty(facultyId):
    authenticate(ALL_ROLES)
    return success_obj(db.public(require_faculty(facultyId)), 200)


@bp.patch("/faculty-members/<facultyId>")
def patch_faculty(facultyId):
    authenticate([CHAIR])
    body = body_json()
    check_shape(body, {
        "status": {"type": "enum", "values": FACULTY_STATUSES},
        "base_load_credits": {"type": "number"},
        "preferred_course_ids": {"type": "string_array"},
    })
    faculty = require_faculty(facultyId)
    new_status = body.get("status")
    status_change = present(body, "status") and new_status != faculty["status"]
    if present(body, "status") and (faculty["status"], new_status) not in _ALLOWED_TRANSITIONS:
        raise ApiError(
            ERR_INVALID_FACULTY_STATE, 409,
            f"cannot move faculty from {faculty['status']} to {new_status}",
        )
    base_load_changed = (present(body, "base_load_credits")
                         and body["base_load_credits"] != faculty["base_load_credits"])
    # Apply field edits, then the status change, as one faculty mutation.
    if present(body, "base_load_credits"):
        faculty["base_load_credits"] = body["base_load_credits"]
    if present(body, "preferred_course_ids"):
        faculty["preferred_course_ids"] = list(body["preferred_course_ids"])
    if status_change:
        faculty["status"] = new_status
    db.touch(faculty)
    # Leave/separation cascade (PRD §3.2) then, if the contractual load moved,
    # a recompute of every load sheet of this faculty (auto-withdraw included).
    if status_change and new_status in ("ON_LEAVE", "SEPARATED"):
        services.faculty_leave_cascade(faculty)
    if base_load_changed:
        services.recompute_faculty_sheets(faculty["id"])
    return success_obj(db.public(faculty), 200)
