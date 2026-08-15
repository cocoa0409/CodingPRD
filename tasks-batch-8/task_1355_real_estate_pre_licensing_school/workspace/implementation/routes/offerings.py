"""CourseOffering endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import (
    require_roles, get_json_body, parse_pagination, parse_date,
    check_director_scope, validate_enum, validate_int_range,
)
from response import success_object, success_list
from services.calculations import update_offering_counts, _extract_date
from services.cascade import cancel_offering_cascade
from datetime import timedelta

bp = Blueprint("offerings", __name__)

DELIVERY_MODES = {"IN_PERSON", "DISTANCE"}


def _offering_to_json(o):
    return {k: v for k, v in o.items()}


def _get_offering(offering_id):
    o = db.offerings.get(offering_id)
    if not o:
        errors.raise_error(errors.ERR_OFFERING_NOT_FOUND, f"Offering {offering_id} not found")
    return o


def _check_instructor_rest_gap(instructor_id, new_start, new_end, exclude_offering_id=None):
    """Check instructor rest-day rule: one full rest day between windows.
    Conflict unless new.start >= existing.end + 2 days OR new.end + 2 days <= existing.start.
    """
    for o in db.offerings.values():
        if o["instructor_id"] != instructor_id:
            continue
        if o["status"] == "CANCELLED":
            continue
        if exclude_offering_id and o["id"] == exclude_offering_id:
            continue
        existing_start = _extract_date(o["start_date"])
        existing_end = _extract_date(o["end_date"])
        if existing_start is None or existing_end is None:
            continue
        if new_start >= existing_end + timedelta(days=2):
            continue
        if new_end + timedelta(days=2) <= existing_start:
            continue
        errors.raise_error(errors.ERR_INSTRUCTOR_SCHEDULE_CONFLICT,
                           "Instructor has a conflicting offering (rest-day rule)")


@bp.route("/offerings", methods=["POST"])
@require_roles("SchoolDirector")
def create_offering():
    body = get_json_body(
        required_fields=["course_id", "instructor_id", "state_code",
                         "start_date", "end_date", "capacity", "delivery_mode"],
    )
    auth = request.auth

    # Existence
    course = db.courses.get(body["course_id"])
    if not course:
        errors.raise_error(errors.ERR_COURSE_NOT_FOUND, f"Course {body['course_id']} not found")

    instructor = db.instructors.get(body["instructor_id"])
    if not instructor:
        errors.raise_error(errors.ERR_INSTRUCTOR_NOT_FOUND, f"Instructor {body['instructor_id']} not found")

    # Scope: director must own school's course
    school = db.schools.get(course["school_id"])
    if school:
        check_director_scope(school, auth)

    # Shape validations
    validate_enum(body["delivery_mode"], DELIVERY_MODES, "delivery_mode")

    if not isinstance(body["capacity"], int) or isinstance(body["capacity"], bool) or body["capacity"] < 1:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "capacity must be >= 1")

    start_date = parse_date(body["start_date"], "start_date")
    end_date = parse_date(body["end_date"], "end_date")

    # State: course must be ACTIVE
    if course["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_COURSE_NOT_ACTIVE,
                           f"Course status is {course['status']}, expected ACTIVE")

    # Temporal: window valid
    if end_date < start_date:
        errors.raise_error(errors.ERR_INVALID_OFFERING_WINDOW,
                           "end_date must be >= start_date")
    if start_date < db.today():
        errors.raise_error(errors.ERR_INVALID_OFFERING_WINDOW,
                           "start_date must be >= today")

    # Instructor rest-gap
    _check_instructor_rest_gap(body["instructor_id"], start_date, end_date)

    offering = db.new_entity({
        "course_id": body["course_id"],
        "instructor_id": body["instructor_id"],
        "state_code": body["state_code"],
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "capacity": body["capacity"],
        "delivery_mode": body["delivery_mode"],
        "status": "DRAFT",
        "enrolled_count": 0,
        "seats_available": body["capacity"],
    })
    db.offerings[offering["id"]] = offering
    db.audit("CourseOffering", offering["id"], "OFFERING_CREATED",
             auth["role"], auth["user_id"])
    return success_object(_offering_to_json(offering), 201)


@bp.route("/offerings", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Student")
def list_offerings():
    limit, offset = parse_pagination()
    items = list(db.offerings.values())

    # Filters
    school_id = request.args.get("school_id")
    if school_id:
        course_ids = {c["id"] for c in db.courses.values() if c["school_id"] == school_id}
        items = [o for o in items if o["course_id"] in course_ids]

    course_id = request.args.get("course_id")
    if course_id:
        items = [o for o in items if o["course_id"] == course_id]

    instructor_id = request.args.get("instructor_id")
    if instructor_id:
        items = [o for o in items if o["instructor_id"] == instructor_id]

    state_code = request.args.get("state_code")
    if state_code:
        items = [o for o in items if o["state_code"] == state_code]

    status_filter = request.args.get("status")
    if status_filter:
        items = [o for o in items if o["status"] == status_filter]

    # Director scope
    auth = request.auth
    if auth["role"] == "SchoolDirector":
        own_school_ids = {s["id"] for s in db.schools.values() if s.get("director_user_id") == auth["user_id"]}
        own_course_ids = {c["id"] for c in db.courses.values() if c["school_id"] in own_school_ids}
        items = [o for o in items if o["course_id"] in own_course_ids]

    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_offering_to_json(o) for o in page], limit, offset, total)


@bp.route("/offerings/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Student")
def get_offering(id):
    offering = _get_offering(id)
    return success_object(_offering_to_json(offering))


@bp.route("/offerings/<id>", methods=["PUT"])
@require_roles("SchoolDirector")
def update_offering(id):
    offering = _get_offering(id)
    auth = request.auth

    # Scope: director must own school
    course = db.courses.get(offering["course_id"])
    if course:
        school = db.schools.get(course["school_id"])
        if school:
            check_director_scope(school, auth)

    body = get_json_body(
        required_fields=["expected_offering_version"],
        optional_fields=["start_date", "end_date", "capacity"],
    )

    # OCC check
    expected = body["expected_offering_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "expected_offering_version must be an integer")
    if expected != offering["version"]:
        errors.raise_error(errors.ERR_STALE_OFFERING_VERSION,
                           f"Expected version {expected}, current {offering['version']}")

    # State: must be DRAFT or PUBLISHED
    if offering["status"] not in ("DRAFT", "PUBLISHED"):
        errors.raise_error(errors.ERR_ENROLLMENT_STATE_INVALID,
                           f"Offering status is {offering['status']}, cannot update")

    # Apply updates
    new_start = offering["start_date"]
    new_end = offering["end_date"]
    new_capacity = offering["capacity"]

    if "start_date" in body:
        start_d = parse_date(body["start_date"], "start_date")
        new_start = body["start_date"]
    else:
        start_d = _extract_date(offering["start_date"])

    if "end_date" in body:
        end_d = parse_date(body["end_date"], "end_date")
        new_end = body["end_date"]
    else:
        end_d = _extract_date(offering["end_date"])

    if "capacity" in body:
        if not isinstance(body["capacity"], int) or isinstance(body["capacity"], bool) or body["capacity"] < 1:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "capacity must be >= 1")
        new_capacity = body["capacity"]

    # Temporal: window valid
    if end_d < start_d:
        errors.raise_error(errors.ERR_INVALID_OFFERING_WINDOW, "end_date < start_date")
    if start_d < db.today():
        errors.raise_error(errors.ERR_INVALID_OFFERING_WINDOW, "start_date < today")

    # Capacity check
    if new_capacity < offering["enrolled_count"]:
        errors.raise_error(errors.ERR_CAPACITY_BELOW_ENROLLED,
                           f"capacity {new_capacity} < enrolled_count {offering['enrolled_count']}")

    # Instructor rest-gap (excluding self)
    _check_instructor_rest_gap(offering["instructor_id"], start_d, end_d, exclude_offering_id=id)

    # Apply
    offering["start_date"] = new_start
    offering["end_date"] = new_end
    offering["capacity"] = new_capacity
    update_offering_counts(offering)
    db.touch(offering)
    db.audit("CourseOffering", offering["id"], "OFFERING_UPDATED",
             auth["role"], auth["user_id"])
    return success_object(_offering_to_json(offering))


@bp.route("/offerings/<id>/publish", methods=["POST"])
@require_roles("SchoolDirector")
def publish_offering(id):
    offering = _get_offering(id)
    auth = request.auth

    # Scope
    course = db.courses.get(offering["course_id"])
    if course:
        school = db.schools.get(course["school_id"])
        if school:
            check_director_scope(school, auth)

    # State: must be DRAFT
    if offering["status"] != "DRAFT":
        errors.raise_error(errors.ERR_ENROLLMENT_STATE_INVALID,
                           f"Offering status is {offering['status']}, expected DRAFT")

    # Gate 1: school LICENSED
    school = db.schools.get(course["school_id"]) if course else None
    if school:
        if school["status"] == "REVOKED":
            errors.raise_error(errors.ERR_SCHOOL_TERMINAL, "School is REVOKED")
        if school["status"] != "LICENSED":
            errors.raise_error(errors.ERR_SCHOOL_NOT_LICENSED, "School must be LICENSED")

    # Gate 2: school posture GOOD_STANDING
    if school and school.get("posture") == "PROBATION":
        errors.raise_error(errors.ERR_SCHOOL_ON_PROBATION, "School is on PROBATION")

    # Gate 3: course ACTIVE
    if course and course["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_COURSE_NOT_ACTIVE, "Course must be ACTIVE")

    # Gate 4: course authorized in state
    state_code = offering["state_code"]
    has_course_approval = any(
        a["course_id"] == offering["course_id"] and a["state_code"] == state_code and a["status"] == "APPROVED"
        for a in db.course_approvals.values()
    )
    has_grant = any(
        g["course_id"] == offering["course_id"] and g["recognized_state_code"] == state_code and g["status"] == "ACTIVE"
        for g in db.equivalency_grants.values()
    )
    if not has_course_approval and not has_grant:
        errors.raise_error(errors.ERR_COURSE_NOT_AUTHORIZED_IN_STATE,
                           f"Course not authorized in {state_code}")

    # Gate 5: instructor approved in state
    instructor_id = offering["instructor_id"]
    has_instructor_approval = any(
        a["instructor_id"] == instructor_id and a["state_code"] == state_code and a["status"] == "APPROVED"
        for a in db.instructor_approvals.values()
    )
    if not has_instructor_approval:
        errors.raise_error(errors.ERR_INSTRUCTOR_NOT_APPROVED_IN_STATE,
                           f"Instructor not approved in {state_code}")

    offering["status"] = "PUBLISHED"
    db.touch(offering)
    db.audit("CourseOffering", offering["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "DRAFT", "to_status": "PUBLISHED"})
    return success_object(_offering_to_json(offering))


@bp.route("/offerings/<id>/cancel", methods=["POST"])
@require_roles("SchoolDirector")
def cancel_offering(id):
    offering = _get_offering(id)
    auth = request.auth

    # Scope
    course = db.courses.get(offering["course_id"])
    if course:
        school = db.schools.get(course["school_id"])
        if school:
            check_director_scope(school, auth)

    if offering["status"] not in ("DRAFT", "PUBLISHED", "IN_SESSION"):
        errors.raise_error(errors.ERR_OFFERING_NOT_CANCELLABLE,
                           f"Offering status is {offering['status']}, cannot cancel")

    old_status = offering["status"]
    offering["status"] = "CANCELLED"
    db.touch(offering)
    db.audit("CourseOffering", offering["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": old_status, "to_status": "CANCELLED"})

    # Cascade for PUBLISHED and IN_SESSION
    if old_status in ("PUBLISHED", "IN_SESSION"):
        cancel_offering_cascade(offering, auth["role"], auth["user_id"],
                                from_status=old_status)

    return success_object(_offering_to_json(offering))
