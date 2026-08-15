"""Exam attempt endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import (
    require_roles, get_json_body, parse_pagination,
    check_proctor_scope, check_instructor_scope,
)
from response import success_object, success_list
from services.calculations import compute_exam_attempts_used, _extract_date
from services.cascade import invalidate_exam_attempt

bp = Blueprint("exam_attempts", __name__)


def _attempt_to_json(a):
    return {k: v for k, v in a.items()}


def _get_enrollment(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if not e:
        errors.raise_error(errors.ERR_ENROLLMENT_NOT_FOUND,
                           f"Enrollment {enrollment_id} not found")
    return e


def _get_attempt(attempt_id):
    a = db.exam_attempts.get(attempt_id)
    if not a:
        errors.raise_error(errors.ERR_EXAM_ATTEMPT_NOT_FOUND,
                           f"ExamAttempt {attempt_id} not found")
    return a


def _update_attempts_used(enrollment):
    """Recompute exam_attempts_used on enrollment."""
    enrollment["exam_attempts_used"] = compute_exam_attempts_used(enrollment["id"])
    db.touch(enrollment)


@bp.route("/enrollments/<enrollment_id>/exam-attempts", methods=["POST"])
@require_roles("Registrar")
def create_exam_attempt(enrollment_id):
    enrollment = _get_enrollment(enrollment_id)
    auth = request.auth

    body = get_json_body(required_fields=["scheduled_at", "proctor_instructor_id"])

    # Existence: proctor
    proctor_id = body["proctor_instructor_id"]
    proctor = db.instructors.get(proctor_id)
    if not proctor:
        errors.raise_error(errors.ERR_INSTRUCTOR_NOT_FOUND,
                           f"Instructor {proctor_id} not found")

    # State: enrollment must be SEAT_TIME_MET
    if enrollment["academic_status"] != "SEAT_TIME_MET":
        errors.raise_error(errors.ERR_SEAT_TIME_NOT_MET,
                           f"Enrollment status is {enrollment['academic_status']}, expected SEAT_TIME_MET")

    # Segregation of duties
    offering = db.offerings.get(enrollment["offering_id"])
    if offering and proctor_id == offering["instructor_id"]:
        errors.raise_error(errors.ERR_PROCTOR_IS_INSTRUCTOR,
                           "Proctor must not be the offering's instructor")

    # Attempts exhausted check
    attempts_used = compute_exam_attempts_used(enrollment_id)
    course = db.courses.get(offering["course_id"]) if offering else None
    max_attempts = course["max_exam_attempts"] if course else 2
    if attempts_used >= max_attempts:
        errors.raise_error(errors.ERR_EXAM_ATTEMPTS_EXHAUSTED,
                           f"Exam attempts exhausted ({attempts_used}/{max_attempts})")

    # Proctor schedule conflict: same calendar date, SCHEDULED or PROCTORED
    scheduled_at_str = body["scheduled_at"]
    sched_date = _extract_date(scheduled_at_str)
    if sched_date:
        for att in db.exam_attempts.values():
            if att["proctor_instructor_id"] != proctor_id:
                continue
            if att["status"] not in ("SCHEDULED", "PROCTORED"):
                continue
            att_date = _extract_date(att.get("scheduled_at"))
            if att_date and att_date == sched_date:
                errors.raise_error(errors.ERR_PROCTOR_SCHEDULE_CONFLICT,
                                   "Proctor already has an attempt on this date")

    attempt = db.new_entity({
        "enrollment_id": enrollment_id,
        "attempt_number": attempts_used + 1,
        "scheduled_at": scheduled_at_str,
        "proctor_instructor_id": proctor_id,
        "status": "SCHEDULED",
        "score_pct": None,
        "outcome": None,
        "invalidation_reason": None,
        "verified_at": None,
        "scored_at": None,
    })
    db.exam_attempts[attempt["id"]] = attempt
    db.audit("ExamAttempt", attempt["id"], "EXAM_ATTEMPT_CREATED",
             auth["role"], auth["user_id"])

    _update_attempts_used(enrollment)

    return success_object(_attempt_to_json(attempt), 201)


@bp.route("/enrollments/<enrollment_id>/exam-attempts", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Student")
def list_enrollment_attempts(enrollment_id):
    enrollment = _get_enrollment(enrollment_id)
    auth = request.auth

    if auth["role"] == "Student":
        if enrollment["student_id"] != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own enrollment")

    limit, offset = parse_pagination()
    items = [a for a in db.exam_attempts.values() if a["enrollment_id"] == enrollment_id]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_attempt_to_json(a) for a in page], limit, offset, total)


@bp.route("/exam-attempts", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def list_exam_attempts():
    limit, offset = parse_pagination()
    items = list(db.exam_attempts.values())

    proctor_id = request.args.get("proctor_instructor_id")
    if proctor_id:
        items = [a for a in items if a["proctor_instructor_id"] == proctor_id]

    enrollment_id = request.args.get("enrollment_id")
    if enrollment_id:
        items = [a for a in items if a["enrollment_id"] == enrollment_id]

    status_filter = request.args.get("status")
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]

    # Director scope
    auth = request.auth
    if auth["role"] == "SchoolDirector":
        own_school_ids = {s["id"] for s in db.schools.values() if s.get("director_user_id") == auth["user_id"]}
        own_course_ids = {c["id"] for c in db.courses.values() if c["school_id"] in own_school_ids}
        own_offering_ids = {o["id"] for o in db.offerings.values() if o["course_id"] in own_course_ids}
        own_enrollment_ids = {e["id"] for e in db.enrollments.values() if e["offering_id"] in own_offering_ids}
        items = [a for a in items if a["enrollment_id"] in own_enrollment_ids]

    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_attempt_to_json(a) for a in page], limit, offset, total)


@bp.route("/exam-attempts/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Proctor")
def get_exam_attempt(id):
    attempt = _get_attempt(id)
    auth = request.auth

    if auth["role"] == "Proctor":
        check_proctor_scope(attempt["proctor_instructor_id"], auth)

    if auth["role"] == "SchoolDirector":
        enrollment = db.enrollments.get(attempt["enrollment_id"])
        if enrollment:
            offering = db.offerings.get(enrollment["offering_id"])
            if offering:
                course = db.courses.get(offering["course_id"])
                if course:
                    school = db.schools.get(course["school_id"])
                    if school and school.get("director_user_id") != auth["user_id"]:
                        errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own school")

    return success_object(_attempt_to_json(attempt))


@bp.route("/exam-attempts/<id>/verify", methods=["POST"])
@require_roles("Proctor")
def verify_exam_attempt(id):
    attempt = _get_attempt(id)
    auth = request.auth

    # Scope: must be the assigned proctor
    check_proctor_scope(attempt["proctor_instructor_id"], auth)

    if attempt["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_EXAM_ATTEMPT_STATE_INVALID,
                           f"Attempt status is {attempt['status']}, expected SCHEDULED")

    attempt["status"] = "PROCTORED"
    attempt["verified_at"] = db.now_iso()
    db.touch(attempt)
    db.audit("ExamAttempt", attempt["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "SCHEDULED", "to_status": "PROCTORED"})

    return success_object(_attempt_to_json(attempt))


@bp.route("/exam-attempts/<id>/score", methods=["POST"])
@require_roles("Instructor")
def score_exam_attempt(id):
    attempt = _get_attempt(id)
    auth = request.auth

    # Scope: must be the offering's instructor
    enrollment = db.enrollments.get(attempt["enrollment_id"])
    if not enrollment:
        errors.raise_error(errors.ERR_ENROLLMENT_NOT_FOUND, "Enrollment not found")
    offering = db.offerings.get(enrollment["offering_id"])
    if not offering:
        errors.raise_error(errors.ERR_OFFERING_NOT_FOUND, "Offering not found")

    check_instructor_scope(offering["instructor_id"], auth)

    body = get_json_body(required_fields=["score_pct"])

    score_pct = body["score_pct"]
    if not isinstance(score_pct, int) or isinstance(score_pct, bool):
        errors.raise_error(errors.ERR_SCORE_OUT_OF_RANGE,
                           "score_pct must be an integer")
    if score_pct < 0 or score_pct > 100:
        errors.raise_error(errors.ERR_SCORE_OUT_OF_RANGE,
                           "score_pct must be 0..100")

    if attempt["status"] != "PROCTORED":
        errors.raise_error(errors.ERR_EXAM_ATTEMPT_STATE_INVALID,
                           f"Attempt status is {attempt['status']}, expected PROCTORED")

    # Compute outcome
    course = db.courses.get(offering["course_id"])
    pass_score = course["pass_score_pct"] if course else 70
    outcome = "PASSED" if score_pct >= pass_score else "FAILED"

    attempt["status"] = "SCORED"
    attempt["score_pct"] = score_pct
    attempt["outcome"] = outcome
    attempt["scored_at"] = db.now_iso()
    db.touch(attempt)
    db.audit("ExamAttempt", attempt["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "PROCTORED", "to_status": "SCORED",
              "note": f"outcome={outcome}"})

    # Enrollment transitions
    _update_attempts_used(enrollment)

    if outcome == "PASSED":
        if enrollment["academic_status"] == "SEAT_TIME_MET":
            enrollment["academic_status"] = "EXAM_PASSED"
            db.touch(enrollment)
            db.audit("Enrollment", enrollment["id"], "STATUS_CHANGE",
                     "system", "system",
                     {"from_status": "SEAT_TIME_MET", "to_status": "EXAM_PASSED"})
    else:
        # FAILED: check if last attempt
        if enrollment["academic_status"] == "SEAT_TIME_MET":
            if enrollment["exam_attempts_used"] >= (course["max_exam_attempts"] if course else 2):
                enrollment["academic_status"] = "FAILED"
                db.touch(enrollment)
                db.audit("Enrollment", enrollment["id"], "STATUS_CHANGE",
                         "system", "system",
                         {"from_status": "SEAT_TIME_MET", "to_status": "FAILED"})
                # Recompute offering counts
                update_off = db.offerings.get(enrollment["offering_id"])
                if update_off:
                    from services.calculations import update_offering_counts
                    update_offering_counts(update_off)
                    db.touch(update_off)

    return success_object(_attempt_to_json(attempt))


@bp.route("/exam-attempts/<id>/invalidate", methods=["POST"])
@require_roles("Proctor", "SchoolDirector")
def invalidate_attempt(id):
    attempt = _get_attempt(id)
    auth = request.auth

    body = get_json_body(required_fields=["reason"])

    # Scope: proctor must be assigned proctor; director must own school
    if auth["role"] == "Proctor":
        check_proctor_scope(attempt["proctor_instructor_id"], auth)
    elif auth["role"] == "SchoolDirector":
        enrollment = db.enrollments.get(attempt["enrollment_id"])
        if enrollment:
            offering = db.offerings.get(enrollment["offering_id"])
            if offering:
                course = db.courses.get(offering["course_id"])
                if course:
                    school = db.schools.get(course["school_id"])
                    if school and school.get("director_user_id") != auth["user_id"]:
                        errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own school")

    # State: must be SCHEDULED, PROCTORED, or SCORED
    if attempt["status"] not in ("SCHEDULED", "PROCTORED", "SCORED"):
        errors.raise_error(errors.ERR_EXAM_ATTEMPT_STATE_INVALID,
                           f"Attempt status is {attempt['status']}, cannot invalidate")

    reason = body["reason"]

    # Use cascade helper for invalidation
    invalidate_exam_attempt(attempt, reason, auth["role"], auth["user_id"])

    # Update attempts used on enrollment
    enrollment = db.enrollments.get(attempt["enrollment_id"])
    if enrollment:
        _update_attempts_used(enrollment)

    return success_object(_attempt_to_json(attempt))
