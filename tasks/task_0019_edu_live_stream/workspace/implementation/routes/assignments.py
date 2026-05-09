"""Assignment + Submission endpoints."""
import hashlib

from flask import Blueprint, request

from db import bump, make_common_fields, store
from errors import raise_api
from middleware import require_roles
from response import success
from services.lookup import (
    get_assignment,
    get_chapter,
    get_course,
    get_enrollment,
    get_submission,
)
from services.progress import recompute_progress

assignments_bp = Blueprint("assignments", __name__)

REVISION_CAP = 3
PLAGIARISM_BLOCK_THRESHOLD = 0.8


def _validate_payload(fmt, body):
    pt = body.get("payload_text")
    pf = body.get("payload_file_url")
    pc = body.get("payload_code")
    populated = sum(1 for v in (pt, pf, pc) if v not in (None, ""))
    if populated != 1:
        raise_api("ERR_PAYLOAD_FORMAT_MISMATCH", "Exactly one payload field must be set")
    if fmt == "TEXT" and not pt:
        raise_api("ERR_PAYLOAD_FORMAT_MISMATCH", "Format mismatch")
    if fmt == "FILE" and not pf:
        raise_api("ERR_PAYLOAD_FORMAT_MISMATCH", "Format mismatch")
    if fmt == "CODE" and not pc:
        raise_api("ERR_PAYLOAD_FORMAT_MISMATCH", "Format mismatch")
    return pt, pf, pc


def _compute_plagiarism(payload_text, payload_file_url, payload_code) -> float:
    """Stub plagiarism scorer. Deterministic on content."""
    blob = (payload_text or "") + "|" + (payload_file_url or "") + "|" + (payload_code or "")
    if not blob.strip("|"):
        return 0.0
    h = hashlib.sha256(blob.encode()).hexdigest()
    n = int(h[:8], 16)
    # 0.0..0.5 typical (well under 0.8 threshold)
    return round((n % 1000) / 2000.0, 3)


@assignments_bp.route("/courses/<course_id>/assignments", methods=["POST"])
def publish_assignment(course_id):
    user_id, _ = require_roles("Instructor")
    course = get_course(course_id)
    if course["instructor_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    body = request.get_json(silent=True) or {}
    chapter_id = body.get("chapter_id")
    if chapter_id:
        ch = get_chapter(chapter_id)
        if ch["course_id"] != course_id:
            raise_api("ERR_CHAPTER_NOT_FOUND", "Chapter not under this course")
    title = body.get("title")
    if not title:
        raise_api("ERR_INVALID_PRICING", "title required")
    fmt = body.get("format")
    if fmt not in ("TEXT", "FILE", "CODE"):
        raise_api("ERR_PAYLOAD_FORMAT_MISMATCH", "Invalid format")
    try:
        due_ts = int(body["due_ts"])
    except (KeyError, TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "due_ts required")
    try:
        max_score = int(body["max_score"])
    except (KeyError, TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "max_score required")
    if max_score <= 0:
        raise_api("ERR_INVALID_PRICING", "max_score must be > 0")

    a = {
        **make_common_fields(),
        "course_id": course_id,
        "chapter_id": chapter_id,
        "title": title,
        "format": fmt,
        "due_ts": due_ts,
        "max_score": max_score,
        "status": "PUBLISHED",
    }
    store.assignments[a["id"]] = a
    return success(dict(a), http_status=201)


@assignments_bp.route("/assignments/<assignment_id>/submissions", methods=["POST"])
def create_submission(assignment_id):
    user_id, _ = require_roles("Student")
    a = get_assignment(assignment_id)
    body = request.get_json(silent=True) or {}
    enrollment_id = body.get("enrollment_id")
    if not enrollment_id:
        raise_api("ERR_ENROLLMENT_NOT_FOUND", "enrollment_id required")
    enr = get_enrollment(enrollment_id)
    if enr["student_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the enrollment owner")
    if enr["course_id"] != a["course_id"]:
        raise_api("ERR_ENROLLMENT_NOT_FOUND", "Enrollment is not in this assignment's course")
    pt, pf, pc = _validate_payload(a["format"], body)
    if store.clock_now_ts >= int(a["due_ts"]):
        raise_api("ERR_SUBMISSION_PAST_DUE", "Past due")

    plag = _compute_plagiarism(pt, pf, pc)
    s = {
        **make_common_fields(),
        "assignment_id": assignment_id,
        "enrollment_id": enrollment_id,
        "payload_text": pt,
        "payload_file_url": pf,
        "payload_code": pc,
        "status": "SUBMITTED",
        "revision_count": 0,
        "plagiarism_score": plag,
        "score": None,
        "feedback": None,
    }
    store.submissions[s["id"]] = s
    return success(dict(s), http_status=201)


@assignments_bp.route("/submissions/<sub_id>/payload", methods=["PUT"])
def resubmit_payload(sub_id):
    user_id, _ = require_roles("Student")
    s = get_submission(sub_id)
    if s["status"] != "REVISION_REQUESTED":
        raise_api("ERR_SUBMISSION_NOT_AWAITING_REVISION", "Submission must be REVISION_REQUESTED")
    enr = get_enrollment(s["enrollment_id"])
    if enr["student_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the enrollment owner")
    a = get_assignment(s["assignment_id"])
    body = request.get_json(silent=True) or {}
    pt, pf, pc = _validate_payload(a["format"], body)
    if store.clock_now_ts >= int(a["due_ts"]):
        raise_api("ERR_SUBMISSION_PAST_DUE", "Past due")
    s["payload_text"] = pt
    s["payload_file_url"] = pf
    s["payload_code"] = pc
    s["status"] = "SUBMITTED"
    s["revision_count"] = int(s.get("revision_count", 0)) + 1
    s["plagiarism_score"] = _compute_plagiarism(pt, pf, pc)
    bump(s)
    return success(dict(s))


@assignments_bp.route("/submissions/<sub_id>/start-review", methods=["POST"])
def start_review(sub_id):
    user_id, role = require_roles("Instructor", "TeachingAssistant")
    s = get_submission(sub_id)
    if s["status"] != "SUBMITTED":
        raise_api("ERR_SUBMISSION_NOT_SUBMITTED", "Submission must be SUBMITTED")
    enr = get_enrollment(s["enrollment_id"])
    course = get_course(enr["course_id"])
    if role == "Instructor":
        if course["instructor_id"] != user_id:
            raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    else:  # TA
        if enr.get("class_group_id"):
            cg = store.class_groups.get(enr["class_group_id"])
            if not cg or cg.get("ta_instructor_id") != user_id:
                raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the class TA")
        else:
            ok = any(cg.get("ta_instructor_id") == user_id
                     for cg in store.class_groups.values()
                     if cg["course_id"] == course["id"])
            if not ok:
                raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not a TA for this course")
    s["status"] = "UNDER_REVIEW"
    bump(s)
    return success(dict(s))


@assignments_bp.route("/submissions/<sub_id>/request-revision", methods=["POST"])
def request_revision(sub_id):
    user_id, role = require_roles("Instructor", "TeachingAssistant")
    s = get_submission(sub_id)
    enr = get_enrollment(s["enrollment_id"])
    course = get_course(enr["course_id"])
    if role == "Instructor":
        if course["instructor_id"] != user_id:
            raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    else:
        if enr.get("class_group_id"):
            cg = store.class_groups.get(enr["class_group_id"])
            if not cg or cg.get("ta_instructor_id") != user_id:
                raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the class TA")
        else:
            ok = any(cg.get("ta_instructor_id") == user_id
                     for cg in store.class_groups.values()
                     if cg["course_id"] == course["id"])
            if not ok:
                raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not a TA for this course")
    if s["status"] != "UNDER_REVIEW":
        raise_api("ERR_SUBMISSION_NOT_UNDER_REVIEW", "Submission must be UNDER_REVIEW")
    body = request.get_json(silent=True) or {}
    feedback = body.get("feedback")
    if not feedback or not isinstance(feedback, str):
        raise_api("ERR_FEEDBACK_REQUIRED", "feedback required")
    if int(s.get("revision_count", 0)) >= REVISION_CAP:
        raise_api("ERR_REVISION_CAP_REACHED", "Revision cap reached")
    s["status"] = "REVISION_REQUESTED"
    s["feedback"] = feedback
    bump(s)
    return success(dict(s))


@assignments_bp.route("/submissions/<sub_id>/grade", methods=["POST"])
def grade_submission(sub_id):
    user_id, _ = require_roles("Instructor")
    s = get_submission(sub_id)
    enr = get_enrollment(s["enrollment_id"])
    course = get_course(enr["course_id"])
    if course["instructor_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    if s["status"] != "UNDER_REVIEW":
        raise_api("ERR_SUBMISSION_NOT_UNDER_REVIEW", "Submission must be UNDER_REVIEW")
    body = request.get_json(silent=True) or {}
    score_raw = body.get("score")
    feedback = body.get("feedback")
    override = bool(body.get("override_plagiarism", False))

    a = get_assignment(s["assignment_id"])
    if score_raw is None:
        raise_api("ERR_SCORE_OUT_OF_RANGE", "score required")
    try:
        score = int(score_raw)
    except (TypeError, ValueError):
        raise_api("ERR_SCORE_OUT_OF_RANGE", "score must be integer")
    if score < 0 or score > int(a["max_score"]):
        raise_api("ERR_SCORE_OUT_OF_RANGE", f"score must be in [0, {a['max_score']}]")
    if not feedback or not isinstance(feedback, str):
        raise_api("ERR_FEEDBACK_REQUIRED", "feedback required")
    if float(s.get("plagiarism_score", 0.0)) >= PLAGIARISM_BLOCK_THRESHOLD and not override:
        raise_api("ERR_PLAGIARISM_BLOCKED", "Plagiarism score over threshold")

    s["status"] = "GRADED"
    s["score"] = score
    s["feedback"] = feedback
    bump(s)
    recompute_progress(enr, run_at_risk=True)
    return success(dict(s))
