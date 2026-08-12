"""Transcript routes: intake, verify, reject, reads."""
from flask import Blueprint, request

import db
from db import touch
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER)
from middleware import ANY, current_user, require_roles
from response import get_body, paginate, success_object
from services import ser_transcript
from util import GRADE_SCALE, req_date, req_str, to_decimal

bp = Blueprint("transcripts", __name__)

STAFF = ("TransferCenterStaff",)


def _get_transcript(tid):
    rec = db.transcripts.get(tid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"Transcript not found: {tid}")
    return rec


def _check_ownership(rec):
    uid, role = current_user()
    if role == "Student" and rec["student_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Students may only access their own records")


@bp.route("/api/transcripts", methods=["POST"])
@require_roles(*STAFF)
def create_transcript():
    body = get_body()
    student_id = req_str(body, "student_id")
    partner_id = req_str(body, "partner_institution_id")
    term_completed = req_date(body, "term_completed")
    courses = body.get("courses")
    if not isinstance(courses, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "courses must be an array")
    cleaned = []
    for entry in courses:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "each course entry must be an object")
        code = entry.get("external_course_code")
        title = entry.get("title")
        hours = entry.get("credit_hours")
        grade = entry.get("grade")
        if not isinstance(code, str) or code.strip() == "":
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "course entry external_course_code is required")
        if not isinstance(title, str):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "course entry title is required")
        try:
            hours_d = to_decimal(hours)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "course entry credit_hours must be a number")
        if hours_d <= 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "course entry credit_hours must be greater than zero")
        if grade not in GRADE_SCALE:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "course entry grade must be a valid grade letter")
        cleaned.append({
            "external_course_code": code, "title": title,
            "credit_hours": hours, "grade": grade,
        })
    # Body FK existence
    if student_id not in db.students:
        raise ApiError(ERR_NOT_FOUND, 404,
                       f"TransferStudent not found: {student_id}")
    if partner_id not in db.partners:
        raise ApiError(ERR_NOT_FOUND, 404,
                       f"PartnerInstitution not found: {partner_id}")
    rec = db.create_rec(db.transcripts, {
        "student_id": student_id, "partner_institution_id": partner_id,
        "term_completed": term_completed, "courses": cleaned,
        "status": "RECEIVED", "rejection_reason": None, "verified_at": None,
    })
    return success_object(ser_transcript(rec), 201)


@bp.route("/api/transcripts", methods=["GET"])
@require_roles(*ANY)
def list_transcripts():
    uid, role = current_user()
    student_id = request.args.get("student_id")
    partner_id = request.args.get("partner_institution_id")
    status = request.args.get("status")
    recs = list(db.transcripts.values())
    if role == "Student":
        recs = [t for t in recs if t["student_id"] == uid]
    if student_id is not None:
        recs = [t for t in recs if t["student_id"] == student_id]
    if partner_id is not None:
        recs = [t for t in recs if t["partner_institution_id"] == partner_id]
    if status is not None:
        recs = [t for t in recs if t["status"] == status]
    return paginate(recs, ser_transcript)


@bp.route("/api/transcripts/<tid>", methods=["GET"])
@require_roles(*ANY)
def get_transcript(tid):
    rec = _get_transcript(tid)
    _check_ownership(rec)
    return success_object(ser_transcript(rec))


@bp.route("/api/transcripts/<tid>/verify", methods=["POST"])
@require_roles(*STAFF)
def verify_transcript(tid):
    rec = _get_transcript(tid)
    if rec["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a RECEIVED transcript can be verified")
    rec["status"] = "VERIFIED"
    rec["verified_at"] = db.now_iso()
    touch(rec)
    return success_object(ser_transcript(rec))


@bp.route("/api/transcripts/<tid>/reject", methods=["POST"])
@require_roles(*STAFF)
def reject_transcript(tid):
    body = get_body()
    reason = req_str(body, "reason")
    rec = _get_transcript(tid)
    if rec["status"] not in ("RECEIVED", "VERIFIED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a RECEIVED or VERIFIED transcript can be rejected")
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = reason
    touch(rec)
    return success_object(ser_transcript(rec))
