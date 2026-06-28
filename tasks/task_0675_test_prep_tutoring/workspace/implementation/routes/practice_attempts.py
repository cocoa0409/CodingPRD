"""PracticeAttempt endpoints + scoring/void state machine (PRD §3.5)."""
from flask import Blueprint

import db
import response
from errors import err
from middleware import require_auth, get_json_body
from services import serialize, validators, core
from services.calculations import scaled_score, percentile

bp = Blueprint("practice_attempts", __name__)


def _get_attempt_or_404(aid):
    a = db.practice_attempts.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", "Practice attempt not found.")
    return a


@bp.post("/practice-attempts")
def create_attempt():
    user_id, role = require_auth({"Student", "Instructor"})
    body = get_json_body()

    # Existence (priority 3): enrollment_id body FK.
    enrollment_id = validators.require_str(body, "enrollment_id")
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found.")

    # Ownership: a Student may only start attempts on its own enrollments.
    if role == "Student" and enrollment["student_id"] != user_id:
        raise err("ERR_UNAUTHORIZED", "Student does not own this enrollment.")

    # Well-formedness (priority 4).
    attempt_type = validators.require_enum(body, "attempt_type", validators.ATTEMPT_TYPES)
    raw_correct = validators.require_int(body, "raw_correct", minimum=0)
    total_items = validators.require_int(body, "total_items", minimum=1)

    # Score range (priority 18): raw_correct <= total_items and the resulting
    # scaled_score <= Course.baseline_scale_max.
    cohort = db.cohorts[enrollment["cohort_id"]]
    course = db.courses[cohort["course_id"]]
    if raw_correct > total_items:
        raise err("ERR_SCORE_OUT_OF_RANGE", "raw_correct exceeds total_items.")
    prospective = scaled_score(raw_correct, total_items, course["baseline_scale_max"])
    if prospective > course["baseline_scale_max"]:
        raise err("ERR_SCORE_OUT_OF_RANGE", "scaled_score exceeds baseline_scale_max.")

    # PracticeAttempt carries only id + created_at (no updated_at, no version).
    rec = {
        "id": db.new_id(),
        "enrollment_id": enrollment_id,
        "attempt_type": attempt_type,
        "raw_correct": raw_correct,
        "total_items": total_items,
        "scaled_score": None,
        "percentile": None,
        "status": "STARTED",
    }
    db.stamp_create(rec, with_version=False)
    db.practice_attempts[rec["id"]] = rec
    return response.success(serialize.practice_attempt(rec), 201)


@bp.get("/practice-attempts/<aid>")
def get_attempt(aid):
    user_id, role = require_auth({"Student", "Instructor", "Registrar"})
    a = _get_attempt_or_404(aid)
    if role == "Student":
        enrollment = db.enrollments.get(a["enrollment_id"])
        if enrollment is None or enrollment["student_id"] != user_id:
            raise err("ERR_UNAUTHORIZED", "Student does not own this attempt.")
    return response.success(serialize.practice_attempt(a), 200)


@bp.post("/practice-attempts/<aid>/score")
def score_attempt(aid):
    require_auth({"Instructor"})
    a = _get_attempt_or_404(aid)

    # State legality (priority 6).
    if a["status"] != "STARTED":
        raise err("ERR_INVALID_STATE", "Attempt is not STARTED.")

    enrollment = db.enrollments[a["enrollment_id"]]
    cohort = db.cohorts[enrollment["cohort_id"]]
    course = db.courses[cohort["course_id"]]

    # Score range (priority 18) before enrollment-scorable per validation order:
    # priority 18 ERR_SCORE_OUT_OF_RANGE is a higher number than the state check
    # but the PRD §3.5 lists range then enrollment-scorable. ERR_ENROLLMENT_
    # NOT_SCORABLE (409) is business-state; order per PRD §3.5 text: range first.
    if a["raw_correct"] > a["total_items"]:
        raise err("ERR_SCORE_OUT_OF_RANGE", "raw_correct exceeds total_items.")
    new_scaled = scaled_score(a["raw_correct"], a["total_items"], course["baseline_scale_max"])
    if new_scaled > course["baseline_scale_max"]:
        raise err("ERR_SCORE_OUT_OF_RANGE", "scaled_score exceeds baseline_scale_max.")

    # Parent enrollment must be ACTIVE or COMPLETED.
    if enrollment["status"] not in ("ACTIVE", "COMPLETED"):
        raise err("ERR_ENROLLMENT_NOT_SCORABLE", "Enrollment is not scorable.")

    a["scaled_score"] = new_scaled
    a["percentile"] = percentile(new_scaled, course["baseline_scale_max"])
    a["status"] = "COMPLETED"
    # PracticeAttempt has no updated_at/version; status mutation is in-place.

    student = db.students[enrollment["student_id"]]
    if a["attempt_type"] == "DIAGNOSTIC" and student["diagnostic_score"] is None:
        student["diagnostic_score"] = new_scaled
        db.touch(student)
    elif a["attempt_type"] == "PRACTICE":
        core.recompute_practice_aggregates(enrollment)

    return response.success(serialize.practice_attempt(a), 200)


@bp.post("/practice-attempts/<aid>/void")
def void_attempt(aid):
    require_auth({"Instructor"})
    a = _get_attempt_or_404(aid)
    if a["status"] != "STARTED":
        raise err("ERR_INVALID_STATE", "Attempt is not STARTED.")
    a["status"] = "VOIDED"
    return response.success(serialize.practice_attempt(a), 200)
