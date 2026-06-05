"""SCORM/xAPI TrackingSession endpoints (PRD §3.6)."""

from flask import Blueprint, request

import errors
import serializers as ser
from db import db
from middleware import authenticate, require_roles, ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER
from response import object_response, array_response
from services.common import (
    require_body, req_field, opt_field, check_enum, check_score, check_int,
    stamp_create, touch, get_or_404, parse_pagination, paginate, report_set,
)
from services import enrollment_engine as engine
from timeutil import is_strictly_after

bp = Blueprint("tracking_sessions", __name__)

LESSON_STATUSES = {"INCOMPLETE", "COMPLETED", "PASSED", "FAILED"}


def _can_see_enrollment(principal, enrollment):
    if principal.is_admin:
        return True
    if principal.is_learner:
        return enrollment["employee_id"] == principal.user_id
    if principal.is_manager:
        return enrollment["employee_id"] in report_set(principal.user_id)
    return False


@bp.route("/enrollments/<rid>/tracking-sessions", methods=["POST"])
def open_session(rid):
    p = authenticate()
    require_roles(p, [ROLE_LEARNER])
    enr = get_or_404(db.enrollments, rid)
    # ownership
    if enr["employee_id"] != p.user_id:
        raise errors.unauthorized("Learner does not own this enrollment")
    # state gate: enrollment must be IN_PROGRESS
    if enr["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Enrollment not IN_PROGRESS")
    # at most one non-TERMINATED session per enrollment
    for s in db.tracking_sessions.values():
        if s["enrollment_id"] == rid and s["status"] != "TERMINATED":
            raise errors.ApiError(errors.ERR_SESSION_ALREADY_OPEN, 409,
                                  "A non-terminated session already exists")
    course = db.courses.get(enr["course_id"])
    rec = {
        "enrollment_id": rid,
        "content_type": course["content_type"] if course else None,
        "started_at": db.now(),
        "terminated_at": None,
        "lesson_status": None,
        "progress_pct": 0,
        "reported_score": None,
        "status": "INITIALIZED",
    }
    stamp_create(rec)
    db.tracking_sessions[rec["id"]] = rec
    return object_response(ser.tracking_session(rec), status=201)


@bp.route("/enrollments/<rid>/tracking-sessions", methods=["GET"])
def list_sessions(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    enr = get_or_404(db.enrollments, rid)
    if not _can_see_enrollment(p, enr):
        raise errors.unauthorized("Out of scope")
    limit, offset = parse_pagination()
    items = [s for s in db.tracking_sessions.values() if s["enrollment_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([ser.tracking_session(s) for s in page], limit, offset, total)


@bp.route("/tracking-sessions/<rid>/commit", methods=["PATCH"])
def commit_session(rid):
    p = authenticate()
    require_roles(p, [ROLE_LEARNER])
    sess = get_or_404(db.tracking_sessions, rid)
    enr = db.enrollments.get(sess["enrollment_id"])
    # field-shape validation (priority 6) before ownership (priority 7)
    body = require_body()
    lesson_status = check_enum(req_field(body, "lesson_status"), LESSON_STATUSES, "lesson_status")
    progress_pct = req_field(body, "progress_pct")
    check_int(progress_pct, "progress_pct")
    if progress_pct < 0 or progress_pct > 100:
        raise errors.invalid_request("progress_pct must be in 0..100")
    reported_score = opt_field(body, "reported_score", None)
    if reported_score is not None:
        check_score(reported_score, "reported_score")

    # ownership (priority 7)
    if enr is None or enr["employee_id"] != p.user_id:
        raise errors.unauthorized("Learner does not own this session")

    # state gate: INITIALIZED (first commit -> RUNNING) or RUNNING (self-loop)
    if sess["status"] not in ("INITIALIZED", "RUNNING"):
        raise errors.invalid_state("Session not committable")

    sess["lesson_status"] = lesson_status
    sess["progress_pct"] = progress_pct
    sess["reported_score"] = reported_score
    if sess["status"] == "INITIALIZED":
        sess["status"] = "RUNNING"
    touch(sess)
    return object_response(ser.tracking_session(sess))


@bp.route("/tracking-sessions/<rid>/terminate", methods=["POST"])
def terminate_session(rid):
    p = authenticate()
    require_roles(p, [ROLE_LEARNER])
    sess = get_or_404(db.tracking_sessions, rid)
    enr = db.enrollments.get(sess["enrollment_id"])
    if enr is None or enr["employee_id"] != p.user_id:
        raise errors.unauthorized("Learner does not own this session")

    body = request.get_json(silent=True) or {}
    expected_version = body.get("expected_enrollment_version")
    if expected_version is not None:
        check_int(expected_version, "expected_enrollment_version")

    # state gate: session RUNNING
    if sess["status"] != "RUNNING":
        raise errors.invalid_state("Session not RUNNING")

    now = db.now()
    if not is_strictly_after(now, sess["started_at"]):
        # terminated_at interval end must be strictly after started_at
        raise errors.invalid_state("terminated_at must be strictly after started_at")

    reported_score = sess.get("reported_score")

    # OCC (optional) — applied before promoting score to an attempt
    if reported_score is not None and expected_version is not None:
        if expected_version != enr["version"]:
            raise errors.stale_version("expected_enrollment_version mismatch")

    sess["terminated_at"] = now
    sess["status"] = "TERMINATED"
    touch(sess)

    # promote reported_score to a QuizAttempt and drive the enrollment cascade
    if reported_score is not None:
        course = db.courses.get(enr["course_id"])
        if enr["status"] == "IN_PROGRESS" and enr["attempts_used"] < course["max_attempts"]:
            engine.record_attempt(enr, course, reported_score)
            engine.apply_grading_for_attempt(enr, course, reported_score)
    return object_response(ser.tracking_session(sess))
