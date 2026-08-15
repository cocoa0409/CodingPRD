"""Course endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import (
    require_roles, get_json_body, parse_pagination,
    check_director_scope, validate_enum, validate_int_range,
)
from response import success_object, success_list

bp = Blueprint("courses", __name__)

COURSE_TYPES = {"PRE_LICENSING", "CONTINUING_ED"}


def _course_to_json(c):
    return {k: v for k, v in c.items()}


@bp.route("/courses", methods=["POST"])
@require_roles("SchoolDirector")
def create_course():
    body = get_json_body(
        required_fields=["school_id", "course_code", "title", "course_type",
                         "required_seat_minutes", "tuition_cents", "pass_score_pct",
                         "completion_deadline_days"],
        optional_fields=["max_exam_attempts", "ce_credit_hours"],
    )
    auth = request.auth

    # Existence: school_id
    school = db.schools.get(body["school_id"])
    if not school:
        errors.raise_error(errors.ERR_SCHOOL_NOT_FOUND, f"School {body['school_id']} not found")

    # Scope: director must own school
    check_director_scope(school, auth)

    # State: school must be LICENSED
    if school["status"] == "REVOKED":
        errors.raise_error(errors.ERR_SCHOOL_TERMINAL, "School is REVOKED")
    if school["status"] != "LICENSED":
        errors.raise_error(errors.ERR_SCHOOL_NOT_LICENSED, "School must be LICENSED")

    # Shape validations
    validate_enum(body["course_type"], COURSE_TYPES, "course_type")

    if not isinstance(body["required_seat_minutes"], int) or isinstance(body["required_seat_minutes"], bool) or body["required_seat_minutes"] <= 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "required_seat_minutes must be > 0")

    if not isinstance(body["tuition_cents"], int) or isinstance(body["tuition_cents"], bool) or body["tuition_cents"] < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "tuition_cents must be >= 0")

    if not isinstance(body["pass_score_pct"], int) or isinstance(body["pass_score_pct"], bool) or body["pass_score_pct"] < 1 or body["pass_score_pct"] > 100:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "pass_score_pct must be 1..100")

    if not isinstance(body["completion_deadline_days"], int) or isinstance(body["completion_deadline_days"], bool) or body["completion_deadline_days"] < 1:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "completion_deadline_days must be >= 1")

    max_exam_attempts = body.get("max_exam_attempts", 2)
    if not isinstance(max_exam_attempts, int) or isinstance(max_exam_attempts, bool) or max_exam_attempts < 1:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "max_exam_attempts must be >= 1")

    ce_credit_hours = body.get("ce_credit_hours", 0)
    if not isinstance(ce_credit_hours, (int, float)) or isinstance(ce_credit_hours, bool) or ce_credit_hours < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "ce_credit_hours must be >= 0")

    # Uniqueness: course_code within school
    for c in db.courses.values():
        if c["school_id"] == body["school_id"] and c["course_code"] == body["course_code"]:
            errors.raise_error(errors.ERR_DUPLICATE_COURSE_CODE,
                               f"course_code '{body['course_code']}' already exists in this school")

    course = db.new_entity({
        "school_id": body["school_id"],
        "course_code": body["course_code"],
        "title": body["title"],
        "course_type": body["course_type"],
        "required_seat_minutes": body["required_seat_minutes"],
        "tuition_cents": body["tuition_cents"],
        "pass_score_pct": body["pass_score_pct"],
        "max_exam_attempts": max_exam_attempts,
        "completion_deadline_days": body["completion_deadline_days"],
        "ce_credit_hours": ce_credit_hours,
        "status": "DRAFT",
    })
    db.courses[course["id"]] = course
    db.audit("Course", course["id"], "COURSE_CREATED", auth["role"], auth["user_id"])
    return success_object(_course_to_json(course), 201)


@bp.route("/courses", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def list_courses():
    limit, offset = parse_pagination()
    items = list(db.courses.values())

    school_id = request.args.get("school_id")
    if school_id:
        items = [c for c in items if c["school_id"] == school_id]

    status_filter = request.args.get("status")
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]

    course_type = request.args.get("course_type")
    if course_type:
        items = [c for c in items if c["course_type"] == course_type]

    # Director scope
    auth = request.auth
    if auth["role"] == "SchoolDirector":
        own_school_ids = {s["id"] for s in db.schools.values() if s.get("director_user_id") == auth["user_id"]}
        items = [c for c in items if c["school_id"] in own_school_ids]

    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_course_to_json(c) for c in page], limit, offset, total)


@bp.route("/courses/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def get_course(id):
    course = db.courses.get(id)
    if not course:
        errors.raise_error(errors.ERR_COURSE_NOT_FOUND, f"Course {id} not found")
    auth = request.auth
    school = db.schools.get(course["school_id"])
    if school:
        check_director_scope(school, auth)
    return success_object(_course_to_json(course))


@bp.route("/courses/<id>/activate", methods=["POST"])
@require_roles("SchoolDirector")
def activate_course(id):
    course = db.courses.get(id)
    if not course:
        errors.raise_error(errors.ERR_COURSE_NOT_FOUND, f"Course {id} not found")
    auth = request.auth
    school = db.schools.get(course["school_id"])
    if school:
        check_director_scope(school, auth)

    if course["status"] != "DRAFT":
        errors.raise_error(errors.ERR_COURSE_NOT_ACTIVE,
                           f"Course status is {course['status']}, expected DRAFT")

    # Check at least one APPROVED approval
    has_approved = any(
        a["course_id"] == id and a["status"] == "APPROVED"
        for a in db.course_approvals.values()
    )
    if not has_approved:
        errors.raise_error(errors.ERR_COURSE_NOT_APPROVED_ANYWHERE,
                           "Course has no APPROVED approval")

    course["status"] = "ACTIVE"
    db.touch(course)
    db.audit("Course", course["id"], "STATUS_CHANGE", auth["role"], auth["user_id"],
             {"from_status": "DRAFT", "to_status": "ACTIVE"})
    return success_object(_course_to_json(course))


@bp.route("/courses/<id>/retire", methods=["POST"])
@require_roles("SchoolDirector")
def retire_course(id):
    course = db.courses.get(id)
    if not course:
        errors.raise_error(errors.ERR_COURSE_NOT_FOUND, f"Course {id} not found")
    auth = request.auth
    school = db.schools.get(course["school_id"])
    if school:
        check_director_scope(school, auth)

    if course["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_COURSE_NOT_ACTIVE,
                           f"Course status is {course['status']}, expected ACTIVE")

    # Check no open offerings
    open_offerings = any(
        o["course_id"] == id and o["status"] in ("DRAFT", "PUBLISHED", "IN_SESSION")
        for o in db.offerings.values()
    )
    if open_offerings:
        errors.raise_error(errors.ERR_COURSE_HAS_OPEN_OFFERINGS,
                           "Course has open offerings")

    course["status"] = "RETIRED"
    db.touch(course)
    db.audit("Course", course["id"], "STATUS_CHANGE", auth["role"], auth["user_id"],
             {"from_status": "ACTIVE", "to_status": "RETIRED"})
    return success_object(_course_to_json(course))
