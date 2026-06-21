"""Enrollment endpoints + quiz attempts (PRD §3.4, §3.5)."""

from flask import Blueprint, request

import errors
import serializers as ser
from db import db
from middleware import authenticate, require_roles, ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER
from response import object_response, array_response
from services.common import (
    require_body, req_field, opt_field, check_bool, check_nonneg_int, check_score,
    check_int, stamp_create, touch, fk_or_404, get_or_404, parse_pagination,
    paginate, report_set,
)
from services import calculations as calc
from services import enrollment_engine as engine
from timeutil import add_days

bp = Blueprint("enrollments", __name__)

OPEN_CYCLE_STATES = ("NOT_STARTED", "IN_PROGRESS", "FAILED", "EXPIRED")


def _scope_filter_enrollments(principal, items):
    if principal.is_admin:
        return items
    if principal.is_manager:
        scope = report_set(principal.user_id)
        return [e for e in items if e["employee_id"] in scope]
    if principal.is_learner:
        return [e for e in items if e["employee_id"] == principal.user_id]
    return []


@bp.route("/enrollments", methods=["POST"])
def create_enrollment():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_LEARNER])
    body = require_body()
    employee_id = req_field(body, "employee_id")
    course_id = req_field(body, "course_id")
    fk_or_404(db.employees, employee_id)
    fk_or_404(db.courses, course_id)
    is_required = opt_field(body, "is_required", True)
    check_bool(is_required, "is_required")
    due_in_days = opt_field(body, "due_in_days", 30)
    check_nonneg_int(due_in_days, "due_in_days")

    # ownership: a Learner can only self-enroll
    if p.is_learner and employee_id != p.user_id:
        raise errors.unauthorized("Learner may only self-enroll")

    # duplicate open-cycle enrollment for (employee, course)
    for e in db.enrollments.values():
        if (e["employee_id"] == employee_id and e["course_id"] == course_id
                and e["status"] in OPEN_CYCLE_STATES):
            raise errors.duplicate("Open-cycle enrollment already exists")

    due_date = add_days(db.now(), due_in_days)
    rec = {
        "employee_id": employee_id,
        "course_id": course_id,
        "path_enrollment_id": None,
        "assignment_rule_id": None,
        "is_required": is_required,
        "due_date": due_date,
        "best_score": None,
        "latest_score": None,
        "final_grade": None,
        "attempts_used": 0,
        "cycle_index": 1,
        "escalation_tier": 0,
        "certificate_id": None,
        "status": "NOT_STARTED",
    }
    stamp_create(rec)
    db.enrollments[rec["id"]] = rec
    return object_response(ser.enrollment(rec), status=201)


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    limit, offset = parse_pagination()
    items = list(db.enrollments.values())
    for field in ("employee_id", "course_id", "assignment_rule_id", "path_enrollment_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [e for e in items if e.get(field) == val]
    items = _scope_filter_enrollments(p, items)
    page, total = paginate(items, limit, offset)
    return array_response([ser.enrollment(e) for e in page], limit, offset, total)


@bp.route("/enrollments/<rid>", methods=["GET"])
def get_enrollment(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    rec = get_or_404(db.enrollments, rid)
    if not _can_see_enrollment(p, rec):
        raise errors.unauthorized("Out of scope")
    return object_response(ser.enrollment(rec))


def _can_see_enrollment(principal, enrollment):
    if principal.is_admin:
        return True
    if principal.is_learner:
        return enrollment["employee_id"] == principal.user_id
    if principal.is_manager:
        return enrollment["employee_id"] in report_set(principal.user_id)
    return False


@bp.route("/enrollments/<rid>/start", methods=["POST"])
def start_enrollment(rid):
    p = authenticate()
    require_roles(p, [ROLE_LEARNER])
    rec = get_or_404(db.enrollments, rid)

    # ownership (priority 7)
    if rec["employee_id"] != p.user_id:
        raise errors.unauthorized("Learner does not own this enrollment")
    # state gate (priority 8)
    if rec["status"] != "NOT_STARTED":
        raise errors.invalid_state("Enrollment not in NOT_STARTED")
    # course published (priority 10)
    course = db.courses.get(rec["course_id"])
    if course is None or course["status"] != "PUBLISHED":
        raise errors.ApiError(errors.ERR_COURSE_NOT_PUBLISHED, 409, "Course not PUBLISHED")
    # prerequisite gate (priority 11)
    if not _prerequisites_met(rec["course_id"], rec["employee_id"]):
        raise errors.ApiError(errors.ERR_PREREQUISITE_NOT_MET, 409,
                              "Prerequisite certificate(s) missing")
    # path-sequence gate (priority 12)
    if not _path_sequence_ok(rec):
        raise errors.ApiError(errors.ERR_PATH_STEP_LOCKED, 409,
                              "Prior path step not COMPLETED")

    rec["status"] = "IN_PROGRESS"
    touch(rec)
    # bubble owning path enrollment NOT_STARTED -> IN_PROGRESS
    pe_id = rec.get("path_enrollment_id")
    if pe_id:
        pe = db.path_enrollments.get(pe_id)
        if pe is not None:
            engine.reevaluate_path_enrollment(pe)
    return object_response(ser.enrollment(rec))


def _prerequisites_met(course_id, employee_id):
    prereq_ids = [edge["prerequisite_course_id"] for edge in db.course_prerequisites.values()
                  if edge["course_id"] == course_id]
    for pid in prereq_ids:
        has_active = any(
            c["employee_id"] == employee_id and c["course_id"] == pid and c["status"] == "ACTIVE"
            for c in db.certificates.values()
        )
        if not has_active:
            return False
    return True


def _path_sequence_ok(enrollment):
    pe_id = enrollment.get("path_enrollment_id")
    if not pe_id:
        return True
    pe = db.path_enrollments.get(pe_id)
    if pe is None:
        return True
    path = db.learning_paths.get(pe["learning_path_id"])
    if path is None or not path.get("enforce_sequence"):
        return True
    # find this enrollment's step (by course within the path)
    steps = [s for s in db.path_steps.values() if s["learning_path_id"] == path["id"]]
    steps.sort(key=lambda s: s["sequence_index"])
    my_step = None
    for s in steps:
        if s["course_id"] == enrollment["course_id"]:
            my_step = s
            break
    if my_step is None:
        return True
    # prior step (sequence_index - 1)
    prior = [s for s in steps if s["sequence_index"] == my_step["sequence_index"] - 1]
    if not prior:
        return True  # this is the first step
    prior_step = prior[0]
    prior_child = None
    for e in db.enrollments.values():
        if e["path_enrollment_id"] == pe_id and e["course_id"] == prior_step["course_id"]:
            prior_child = e
            break
    if prior_child is None:
        return False
    return prior_child["status"] == "COMPLETED"


# --- quiz attempts --------------------------------------------------------

@bp.route("/enrollments/<rid>/quiz-attempts", methods=["POST"])
def create_quiz_attempt(rid):
    p = authenticate()
    require_roles(p, [ROLE_LEARNER])
    rec = get_or_404(db.enrollments, rid)

    # field-shape validation (priority 6) before ownership (priority 7)
    body = require_body()
    score = req_field(body, "score")
    check_score(score, "score")
    expected_version = req_field(body, "expected_enrollment_version")
    check_int(expected_version, "expected_enrollment_version")

    # ownership (priority 7)
    if rec["employee_id"] != p.user_id:
        raise errors.unauthorized("Learner does not own this enrollment")

    course = db.courses.get(rec["course_id"])

    # state gate (priority 8): reject NOT_STARTED, COMPLETED, EXPIRED, WAIVED
    if rec["status"] not in ("IN_PROGRESS", "FAILED"):
        raise errors.invalid_state("Enrollment does not accept attempts in this state")

    # OCC (priority 9) — before attempts-remaining check
    if expected_version != rec["version"]:
        raise errors.stale_version("expected_enrollment_version mismatch")

    # attempts-remaining (priority 13)
    if rec["status"] != "IN_PROGRESS" or rec["attempts_used"] >= course["max_attempts"]:
        raise errors.ApiError(errors.ERR_ATTEMPTS_EXHAUSTED, 409, "No attempts remaining")

    attempt = engine.record_attempt(rec, course, score)
    engine.apply_grading_for_attempt(rec, course, score)
    return object_response(ser.quiz_attempt(attempt), status=201)


@bp.route("/enrollments/<rid>/quiz-attempts", methods=["GET"])
def list_quiz_attempts(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    rec = get_or_404(db.enrollments, rid)
    if not _can_see_enrollment(p, rec):
        raise errors.unauthorized("Out of scope")
    limit, offset = parse_pagination()
    items = [a for a in db.quiz_attempts.values() if a["enrollment_id"] == rid]
    cycle_index = request.args.get("cycle_index")
    if cycle_index is not None:
        try:
            ci = int(cycle_index)
        except (TypeError, ValueError):
            raise errors.invalid_request("cycle_index must be an integer")
        items = [a for a in items if a["cycle_index"] == ci]
    page, total = paginate(items, limit, offset)
    return array_response([ser.quiz_attempt(a) for a in page], limit, offset, total)


# --- reopen / waive -------------------------------------------------------

@bp.route("/enrollments/<rid>/reopen", methods=["POST"])
def reopen_enrollment(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    rec = get_or_404(db.enrollments, rid)
    if rec["status"] != "FAILED":
        raise errors.invalid_state("Enrollment not in FAILED")
    course = db.courses.get(rec["course_id"])
    if course is None or course["status"] != "PUBLISHED":
        raise errors.ApiError(errors.ERR_COURSE_NOT_PUBLISHED, 409, "Course not PUBLISHED")
    rec["status"] = "IN_PROGRESS"
    rec["attempts_used"] = 0
    rec["best_score"] = None
    rec["latest_score"] = None
    rec["final_grade"] = None
    touch(rec)
    # bubble path enrollment FAILED -> IN_PROGRESS if this step caused failure
    pe_id = rec.get("path_enrollment_id")
    if pe_id:
        pe = db.path_enrollments.get(pe_id)
        if pe is not None:
            engine.reevaluate_path_enrollment(pe)
    return object_response(ser.enrollment(rec))


@bp.route("/enrollments/<rid>/waive", methods=["POST"])
def waive_enrollment(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    rec = get_or_404(db.enrollments, rid)
    if rec["status"] not in ("NOT_STARTED", "IN_PROGRESS", "FAILED", "EXPIRED"):
        raise errors.invalid_state("Enrollment cannot be waived from this state")
    rec["status"] = "WAIVED"
    touch(rec)
    pe_id = rec.get("path_enrollment_id")
    if pe_id:
        pe = db.path_enrollments.get(pe_id)
        if pe is not None:
            engine.reevaluate_path_enrollment(pe)
    # waiver may affect compliance score
    emp = db.employees.get(rec["employee_id"])
    if emp is not None:
        calc.recompute_employee_compliance_score(emp)
    return object_response(ser.enrollment(rec))
