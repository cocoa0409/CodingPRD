"""Assessment routes. PRD 3.7."""
from flask import Blueprint, request

from db import store, common_fields_on_create, touch
from errors import (
    err, ERR_INVALID_REQUEST, ERR_REFERENCE_MISMATCH, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE, ERR_ENROLLMENT_NOT_ACTIVE, ERR_ASSESSMENT_NOT_SUBMITTED,
    ERR_SKILL_SET_MISMATCH, ERR_NOT_READY_TO_ADVANCE, ERR_NO_NEXT_LEVEL,
)
from helpers import get_body, require_str, parse_pagination, paginate
from middleware import get_principal, require_roles
from response import object_response, array_response
from domain import serialize_assessment, withdraw_enrollment, issue_makeup_credit
from lookups import get_enrollment, get_assessment
from calculations import compute_readiness

bp = Blueprint("assessments", __name__)

ALL_ROLES = ["SchoolAdmin", "BillingAdmin", "Instructor", "Parent"]


def _skills_of_level(level_id):
    return [s for s in store.skills.values() if s["level_id"] == level_id]


@bp.route("/assessments", methods=["POST"])
def create_assessment():
    principal = get_principal()
    require_roles(principal, ["Instructor"])
    body = get_body()
    enrollment_id = require_str(body, "enrollment_id")
    skill_scores = body.get("skill_scores", None)
    # Existence first.
    enrollment = get_enrollment(enrollment_id)
    # Validate skill_scores shape (priority 5).
    if skill_scores is None or not isinstance(skill_scores, list):
        err(ERR_INVALID_REQUEST, "skill_scores must be an array")
    for entry in skill_scores:
        if not isinstance(entry, dict) or "skill_id" not in entry or "score" not in entry:
            err(ERR_INVALID_REQUEST, "each skill_score needs skill_id and score")
        if not isinstance(entry["skill_id"], str):
            err(ERR_INVALID_REQUEST, "skill_id must be a string")
        score = entry["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            err(ERR_INVALID_REQUEST, "score must be a number")
        if not (0 <= float(score) <= 1):
            err(ERR_INVALID_REQUEST, "score must be in [0, 1]")
    # priority 4: reference/ownership — the enrollment's session must be taught by
    # the acting instructor (assessment of a child outside the instructor's session
    # is a reference mismatch).
    session = store.class_sessions.get(enrollment["class_session_id"])
    if session is None or session["instructor_id"] != principal.user_id:
        err(ERR_REFERENCE_MISMATCH,
            "Enrollment is not taught by the acting instructor")
    student = store.students.get(enrollment["student_id"])
    assessed_level_id = student["current_level_id"]
    rec = common_fields_on_create()
    rec.update({
        "enrollment_id": enrollment["id"],
        "student_id": enrollment["student_id"],
        "assessed_level_id": assessed_level_id,
        "skill_scores": [{"skill_id": e["skill_id"], "score": e["score"]}
                         for e in skill_scores],
        "mastered_count": 0,
        "weighted_score": 0.0,
        "strict_ready": False,
        "holistic_ready": False,
        "status": "DRAFT",
    })
    store.assessments[rec["id"]] = rec
    return object_response(serialize_assessment(rec), 201)


@bp.route("/assessments", methods=["GET"])
def list_assessments():
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.assessments.values())
    for f in ("enrollment_id", "student_id", "assessed_level_id", "status"):
        val = request.args.get(f)
        if val is not None:
            records = [r for r in records if r[f] == val]
    window, total = paginate(records, limit, offset)
    return array_response([serialize_assessment(r) for r in window], limit, offset, total)


@bp.route("/assessments/<id>", methods=["GET"])
def get_assessment_route(id):
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    rec = get_assessment(id)
    return object_response(serialize_assessment(rec), 200)


@bp.route("/assessments/<id>/submit", methods=["POST"])
def submit_assessment(id):
    principal = get_principal()
    require_roles(principal, ["Instructor"])
    assessment = get_assessment(id)
    enrollment = store.enrollments.get(assessment["enrollment_id"])
    session = store.class_sessions.get(enrollment["class_session_id"]) if enrollment else None
    # priority 6: ownership — acting instructor must teach the enrollment's session.
    if session is None or session["instructor_id"] != principal.user_id:
        err(ERR_NOT_RESOURCE_OWNER, "Instructor must teach the enrollment's session")
    # State legality: only DRAFT -> SUBMITTED.
    if assessment["status"] != "DRAFT":
        err(ERR_INVALID_STATE, "Only a DRAFT assessment may be submitted")
    # priority 8: enrollment must be ACTIVE.
    if enrollment["status"] != "ACTIVE":
        err(ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment is not ACTIVE")
    # skill_scores must cover exactly the assessed level's skill set.
    level_skills = _skills_of_level(assessment["assessed_level_id"])
    level_skill_ids = set(s["id"] for s in level_skills)
    submitted_ids = [e["skill_id"] for e in assessment["skill_scores"]]
    submitted_set = set(submitted_ids)
    if (submitted_set != level_skill_ids) or (len(submitted_ids) != len(level_skill_ids)):
        err(ERR_SKILL_SET_MISMATCH, "skill_scores do not exactly cover the level's skills")

    level = store.levels.get(assessment["assessed_level_id"])
    mastered, weighted, strict_ready, holistic_ready = compute_readiness(
        assessment["skill_scores"], level_skills, level["readiness_threshold"])
    assessment["mastered_count"] = mastered
    assessment["weighted_score"] = weighted
    assessment["strict_ready"] = strict_ready
    assessment["holistic_ready"] = holistic_ready
    assessment["status"] = "SUBMITTED"
    touch(assessment)
    return object_response(serialize_assessment(assessment), 200)


@bp.route("/assessments/<id>/approve", methods=["POST"])
def approve_assessment(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin"])
    assessment = get_assessment(id)
    # State legality: approve requires SUBMITTED.
    if assessment["status"] != "SUBMITTED":
        err(ERR_ASSESSMENT_NOT_SUBMITTED, "Assessment is not SUBMITTED")
    # priority 13: advancement gating.
    if not assessment["strict_ready"]:
        err(ERR_NOT_READY_TO_ADVANCE, "Student not strictly ready to advance")
    level = store.levels.get(assessment["assessed_level_id"])
    if level is None or level["next_level_id"] is None:
        err(ERR_NO_NEXT_LEVEL, "Assessed level has no next level")
    next_level_id = level["next_level_id"]
    assessment["status"] = "APPROVED"
    touch(assessment)
    # CASCADE L1: student.current_level_id -> next_level_id.
    student = store.students.get(assessment["student_id"])
    if student is not None:
        student["current_level_id"] = next_level_id
        touch(student)
        # CASCADE L2: every ACTIVE/PAUSED enrollment whose session level != new
        # current level -> WITHDRAWN, with a LEVEL_TRANSFER_DISRUPTION credit each.
        disrupted = []
        for e in store.enrollments.values():
            if e["student_id"] != student["id"]:
                continue
            if e["status"] not in ("ACTIVE", "PAUSED"):
                continue
            sess = store.class_sessions.get(e["class_session_id"])
            if sess is None:
                continue
            if sess["level_id"] != next_level_id:
                disrupted.append(e)
        disrupted.sort(key=lambda e: (e["created_at"], e["id"]))
        for e in disrupted:
            withdraw_enrollment(e)
            issue_makeup_credit(student["id"], e["id"], "LEVEL_TRANSFER_DISRUPTION")
    return object_response(serialize_assessment(assessment), 200)


@bp.route("/assessments/<id>/reject", methods=["POST"])
def reject_assessment(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin"])
    assessment = get_assessment(id)
    # State legality: reject requires SUBMITTED.
    if assessment["status"] != "SUBMITTED":
        err(ERR_ASSESSMENT_NOT_SUBMITTED, "Assessment is not SUBMITTED")
    # Quiet branch: no level change, no enrollment mutation.
    assessment["status"] = "REJECTED"
    touch(assessment)
    return object_response(serialize_assessment(assessment), 200)
