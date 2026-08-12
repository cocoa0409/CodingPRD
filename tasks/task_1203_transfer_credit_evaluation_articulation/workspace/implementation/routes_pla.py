"""Prior-learning assessment and requirement-application routes."""
from flask import Blueprint, request

import db
from db import touch
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
                    ERR_PLA_CAP_EXCEEDED, ERR_VERIFIED_EXCEEDS_CLAIMED)
from middleware import ANY, current_user, require_roles
from response import get_body, paginate, success_object
from services import (natural_slot_for_course, ser_application, ser_pla)
from util import (MAX_PLA_CREDITS, PLA_SOURCE_TYPES, is_half_step, req_enum,
                  req_number, req_str)

bp = Blueprint("pla", __name__)

EVALUATOR = ("TransferEvaluator",)


def _get_pla(pid):
    rec = db.plas.get(pid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       f"PriorLearningAssessment not found: {pid}")
    return rec


def _get_application(aid):
    rec = db.applications.get(aid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       f"RequirementApplication not found: {aid}")
    return rec


def _check_pla_ownership(rec):
    uid, role = current_user()
    if role == "Student" and rec["student_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Students may only access their own records")


# ---------------------------------------------------------------------------
# Prior learning assessments
# ---------------------------------------------------------------------------

@bp.route("/api/prior-learning-assessments", methods=["POST"])
@require_roles("Student")
def create_pla():
    body = get_body()
    student_id = req_str(body, "student_id")
    source_type = req_enum(body, "source_type", PLA_SOURCE_TYPES)
    credential_ref = req_str(body, "credential_ref")
    claimed = req_number(body, "claimed_credits")
    if claimed <= 0 or not is_half_step(claimed):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "claimed_credits must be > 0 and a multiple of 0.5")
    proposed_id = body.get("proposed_internal_course_id")
    if proposed_id is not None and not isinstance(proposed_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "proposed_internal_course_id must be a string")
    # Body FK existence (priority 4)
    student = db.students.get(student_id)
    if student is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"TransferStudent not found: {student_id}")
    if proposed_id is not None and proposed_id not in db.courses:
        raise ApiError(ERR_NOT_FOUND, 404,
                       f"InternalCourse not found: {proposed_id}")
    # Ownership (priority 6)
    uid, _ = current_user()
    if student_id != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Students may only submit assessments for themselves")
    rec = db.create_rec(db.plas, {
        "student_id": student_id, "source_type": source_type,
        "credential_ref": credential_ref, "claimed_credits": claimed,
        "verified_credits": None,
        "proposed_internal_course_id": proposed_id,
        "status": "SUBMITTED", "rejection_reason": None,
    })
    return success_object(ser_pla(rec), 201)


@bp.route("/api/prior-learning-assessments", methods=["GET"])
@require_roles(*ANY)
def list_plas():
    uid, role = current_user()
    student_id = request.args.get("student_id")
    proposed = request.args.get("proposed_internal_course_id")
    status = request.args.get("status")
    source_type = request.args.get("source_type")
    recs = list(db.plas.values())
    if role == "Student":
        recs = [p for p in recs if p["student_id"] == uid]
    if student_id is not None:
        recs = [p for p in recs if p["student_id"] == student_id]
    if proposed is not None:
        recs = [p for p in recs if p.get("proposed_internal_course_id") == proposed]
    if status is not None:
        recs = [p for p in recs if p["status"] == status]
    if source_type is not None:
        recs = [p for p in recs if p["source_type"] == source_type]
    return paginate(recs, ser_pla)


@bp.route("/api/prior-learning-assessments/<pid>", methods=["GET"])
@require_roles(*ANY)
def get_pla(pid):
    rec = _get_pla(pid)
    _check_pla_ownership(rec)
    return success_object(ser_pla(rec))


@bp.route("/api/prior-learning-assessments/<pid>/verify", methods=["POST"])
@require_roles(*EVALUATOR)
def verify_pla(pid):
    body = get_body()
    verified = req_number(body, "verified_credits")
    if verified <= 0 or not is_half_step(verified):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "verified_credits must be > 0 and a multiple of 0.5")
    rec = _get_pla(pid)
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SUBMITTED assessment can be verified")
    if verified > rec["claimed_credits"]:
        raise ApiError(ERR_VERIFIED_EXCEEDS_CLAIMED, 422,
                       "verified_credits exceeds claimed_credits")
    rec["verified_credits"] = verified
    rec["status"] = "VERIFIED"
    touch(rec)
    return success_object(ser_pla(rec))


@bp.route("/api/prior-learning-assessments/<pid>/credit", methods=["POST"])
@require_roles(*EVALUATOR)
def credit_pla(pid):
    rec = _get_pla(pid)
    if rec["status"] != "VERIFIED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a VERIFIED assessment can be credited")
    student = db.students.get(rec["student_id"])
    # Lifetime PLA cap: exactly-equal is allowed
    if student["total_posted_pla_credits"] + rec["verified_credits"] > MAX_PLA_CREDITS:
        raise ApiError(ERR_PLA_CAP_EXCEEDED, 422,
                       "Crediting would exceed the lifetime PLA cap")
    rec["status"] = "CREDITED"
    touch(rec)
    student["total_posted_pla_credits"] = (
        student["total_posted_pla_credits"] + rec["verified_credits"])
    touch(student)
    course = db.courses.get(rec.get("proposed_internal_course_id") or "")
    slot = natural_slot_for_course(course, student["declared_major"])
    db.create_rec(db.applications, {
        "student_id": student["id"], "line_item_id": None,
        "pla_id": rec["id"], "slot": slot,
        "applied_credits": rec["verified_credits"], "status": "APPLIED",
    })
    return success_object(ser_pla(rec))


@bp.route("/api/prior-learning-assessments/<pid>/reject", methods=["POST"])
@require_roles(*EVALUATOR)
def reject_pla(pid):
    body = get_body()
    reason = req_str(body, "reason")
    rec = _get_pla(pid)
    if rec["status"] not in ("SUBMITTED", "VERIFIED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SUBMITTED or VERIFIED assessment can be rejected")
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = reason
    touch(rec)
    return success_object(ser_pla(rec))


# ---------------------------------------------------------------------------
# Requirement applications (read-only)
# ---------------------------------------------------------------------------

@bp.route("/api/requirement-applications", methods=["GET"])
@require_roles(*ANY)
def list_applications():
    uid, role = current_user()
    student_id = request.args.get("student_id")
    line_item_id = request.args.get("line_item_id")
    pla_id = request.args.get("pla_id")
    slot = request.args.get("slot")
    recs = list(db.applications.values())
    if role == "Student":
        recs = [a for a in recs if a["student_id"] == uid]
    if student_id is not None:
        recs = [a for a in recs if a["student_id"] == student_id]
    if line_item_id is not None:
        recs = [a for a in recs if a.get("line_item_id") == line_item_id]
    if pla_id is not None:
        recs = [a for a in recs if a.get("pla_id") == pla_id]
    if slot is not None:
        recs = [a for a in recs if a["slot"] == slot]
    return paginate(recs, ser_application)


@bp.route("/api/requirement-applications/<aid>", methods=["GET"])
@require_roles(*ANY)
def get_application(aid):
    rec = _get_application(aid)
    uid, role = current_user()
    if role == "Student" and rec["student_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Students may only access their own records")
    return success_object(ser_application(rec))
