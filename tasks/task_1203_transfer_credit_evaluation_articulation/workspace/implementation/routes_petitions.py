"""Petition and appeal routes."""
from datetime import timedelta

import db
from db import touch
from errors import (ApiError, ERR_APPEAL_ADJUDICATOR_CONFLICT,
                    ERR_APPEAL_ALREADY_EXISTS, ERR_APPEAL_NOT_FILEABLE,
                    ERR_APPEAL_WINDOW_EXPIRED, ERR_COURSE_INACTIVE,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_LINE_ITEM_NOT_PETITIONABLE, ERR_NOT_FOUND,
                    ERR_NOT_RESOURCE_OWNER, ERR_PETITION_ALREADY_OPEN,
                    ERR_PETITION_NOT_UNDER_REVIEW)
from flask import Blueprint, request
from middleware import ANY, current_user, require_roles
from response import get_body, paginate, success_object
from services import (adjudicate_appeal, adjudicate_petition_approved,
                      evaluation_of_line, ser_appeal, ser_petition)
from util import APPEAL_WINDOW_DAYS, min_len, parse_dt, req_enum, req_str

bp = Blueprint("petitions", __name__)

ADJUDICATOR = ("FacultyAdjudicator",)


def _get_petition(pid):
    rec = db.petitions.get(pid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"Petition not found: {pid}")
    return rec


def _get_appeal(aid):
    rec = db.appeals.get(aid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"Appeal not found: {aid}")
    return rec


def _check_petition_read_ownership(rec):
    uid, role = current_user()
    if role == "Student" and rec["student_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Students may only access their own records")


# ---------------------------------------------------------------------------
# Petitions
# ---------------------------------------------------------------------------

@bp.route("/api/petitions", methods=["POST"])
@require_roles("Student")
def create_petition():
    body = get_body()
    line_item_id = req_str(body, "line_item_id")
    proposed_id = req_str(body, "proposed_internal_course_id")
    syllabus_ref = req_str(body, "syllabus_ref")
    # Body FK existence (priority 4)
    line = db.lines.get(line_item_id)
    if line is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       f"EvaluationLineItem not found: {line_item_id}")
    course = db.courses.get(proposed_id)
    if course is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       f"InternalCourse not found: {proposed_id}")
    ev = evaluation_of_line(line)
    # Student ownership (priority 6)
    uid, _ = current_user()
    if ev is None or ev["student_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Students may only petition their own line items")
    # Petitionable-state check (priority 14), before uniqueness
    if line["status"] not in ("PETITION_REQUIRED", "DENIED") or \
            ev["status"] not in ("IN_REVIEW", "POSTED"):
        raise ApiError(ERR_LINE_ITEM_NOT_PETITIONABLE, 409,
                       "Line item is not petitionable in its current state")
    # Proposed course must be active (PRD 3.7 order: before open-petition check)
    if not course["is_active"]:
        raise ApiError(ERR_COURSE_INACTIVE, 422,
                       "Referenced internal course is archived")
    # At most one open petition per line item (priority 21)
    for p in db.petitions.values():
        if p["line_item_id"] == line_item_id and p["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            raise ApiError(ERR_PETITION_ALREADY_OPEN, 409,
                           "An open petition already exists for this line item")
    rec = db.create_rec(db.petitions, {
        "line_item_id": line_item_id, "student_id": ev["student_id"],
        "proposed_internal_course_id": proposed_id,
        "syllabus_ref": syllabus_ref, "status": "SUBMITTED",
        "adjudicator_id": None, "adjudication_note": None,
        "awarded_internal_course_id": None, "decided_at": None,
    })
    return success_object(ser_petition(rec), 201)


@bp.route("/api/petitions", methods=["GET"])
@require_roles(*ANY)
def list_petitions():
    uid, role = current_user()
    student_id = request.args.get("student_id")
    line_item_id = request.args.get("line_item_id")
    proposed = request.args.get("proposed_internal_course_id")
    awarded = request.args.get("awarded_internal_course_id")
    status = request.args.get("status")
    recs = list(db.petitions.values())
    if role == "Student":
        recs = [p for p in recs if p["student_id"] == uid]
    if student_id is not None:
        recs = [p for p in recs if p["student_id"] == student_id]
    if line_item_id is not None:
        recs = [p for p in recs if p["line_item_id"] == line_item_id]
    if proposed is not None:
        recs = [p for p in recs if p["proposed_internal_course_id"] == proposed]
    if awarded is not None:
        recs = [p for p in recs if p.get("awarded_internal_course_id") == awarded]
    if status is not None:
        recs = [p for p in recs if p["status"] == status]
    return paginate(recs, ser_petition)


@bp.route("/api/petitions/<pid>", methods=["GET"])
@require_roles(*ANY)
def get_petition(pid):
    rec = _get_petition(pid)
    _check_petition_read_ownership(rec)
    return success_object(ser_petition(rec))


@bp.route("/api/petitions/<pid>/start-review", methods=["POST"])
@require_roles(*ADJUDICATOR)
def petition_start_review(pid):
    rec = _get_petition(pid)
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SUBMITTED petition can move to UNDER_REVIEW")
    uid, _ = current_user()
    rec["status"] = "UNDER_REVIEW"
    rec["adjudicator_id"] = uid
    touch(rec)
    return success_object(ser_petition(rec))


@bp.route("/api/petitions/<pid>/adjudicate", methods=["POST"])
@require_roles(*ADJUDICATOR)
def petition_adjudicate(pid):
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVED", "DENIED"})
    note = min_len(req_str(body, "adjudication_note"), "adjudication_note", 10)
    awarded_id = body.get("awarded_internal_course_id")
    if awarded_id is not None and not isinstance(awarded_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "awarded_internal_course_id must be a string")
    rec = _get_petition(pid)
    awarded_course = None
    if awarded_id is not None:
        awarded_course = db.courses.get(awarded_id)
        if awarded_course is None:
            raise ApiError(ERR_NOT_FOUND, 404,
                           f"InternalCourse not found: {awarded_id}")
    # Priority 11: petition must be UNDER_REVIEW
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_PETITION_NOT_UNDER_REVIEW, 409,
                       "Petition is not UNDER_REVIEW")
    if decision == "APPROVED":
        if awarded_id is not None and not awarded_course["is_active"]:
            raise ApiError(ERR_COURSE_INACTIVE, 422,
                           "Referenced internal course is archived")
        rec["adjudication_note"] = note
        adjudicate_petition_approved(rec, awarded_id)
    else:
        rec["status"] = "DENIED"
        rec["adjudication_note"] = note
        rec["decided_at"] = db.now_iso()
        touch(rec)
    return success_object(ser_petition(rec))


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

@bp.route("/api/appeals", methods=["POST"])
@require_roles("Student")
def create_appeal():
    body = get_body()
    petition_id = req_str(body, "petition_id")
    grounds = min_len(req_str(body, "grounds"), "grounds", 20)
    petition = db.petitions.get(petition_id)
    if petition is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"Petition not found: {petition_id}")
    # Ownership (priority 6)
    uid, _ = current_user()
    if petition["student_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Students may only appeal their own petitions")
    # Priority 15: petition must be DENIED
    if petition["status"] != "DENIED":
        raise ApiError(ERR_APPEAL_NOT_FILEABLE, 409,
                       "Only a DENIED petition can be appealed")
    # Priority 19: appeal window (boundary day inclusive)
    decided_at = parse_dt(petition["decided_at"])
    if db.now() > decided_at + timedelta(days=APPEAL_WINDOW_DAYS):
        raise ApiError(ERR_APPEAL_WINDOW_EXPIRED, 422,
                       "Appeal filed after the appeal window")
    # Priority 22: at most one appeal per petition
    for a in db.appeals.values():
        if a["petition_id"] == petition_id:
            raise ApiError(ERR_APPEAL_ALREADY_EXISTS, 409,
                           "An appeal already exists for this petition")
    rec = db.create_rec(db.appeals, {
        "petition_id": petition_id, "student_id": petition["student_id"],
        "grounds": grounds, "status": "FILED",
        "adjudicator_id": None, "adjudication_note": None, "decided_at": None,
    })
    return success_object(ser_appeal(rec), 201)


@bp.route("/api/appeals", methods=["GET"])
@require_roles(*ANY)
def list_appeals():
    uid, role = current_user()
    petition_id = request.args.get("petition_id")
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    recs = list(db.appeals.values())
    if role == "Student":
        recs = [a for a in recs if a["student_id"] == uid]
    if petition_id is not None:
        recs = [a for a in recs if a["petition_id"] == petition_id]
    if student_id is not None:
        recs = [a for a in recs if a["student_id"] == student_id]
    if status is not None:
        recs = [a for a in recs if a["status"] == status]
    return paginate(recs, ser_appeal)


@bp.route("/api/appeals/<aid>", methods=["GET"])
@require_roles(*ANY)
def get_appeal(aid):
    rec = _get_appeal(aid)
    uid, role = current_user()
    if role == "Student" and rec["student_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Students may only access their own records")
    return success_object(ser_appeal(rec))


@bp.route("/api/appeals/<aid>/start-review", methods=["POST"])
@require_roles(*ADJUDICATOR)
def appeal_start_review(aid):
    rec = _get_appeal(aid)
    if rec["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a FILED appeal can move to UNDER_REVIEW")
    # SoD (priority 28): reviewer must differ from the petition adjudicator
    uid, _ = current_user()
    petition = db.petitions.get(rec["petition_id"])
    if petition is not None and uid == petition.get("adjudicator_id"):
        raise ApiError(ERR_APPEAL_ADJUDICATOR_CONFLICT, 403,
                       "Appeal reviewer must differ from the petition adjudicator")
    rec["status"] = "UNDER_REVIEW"
    rec["adjudicator_id"] = uid
    touch(rec)
    return success_object(ser_appeal(rec))


@bp.route("/api/appeals/<aid>/adjudicate", methods=["POST"])
@require_roles(*ADJUDICATOR)
def appeal_adjudicate(aid):
    body = get_body()
    decision = req_enum(body, "decision", {"UPHELD", "OVERTURNED"})
    note = req_str(body, "adjudication_note")
    rec = _get_appeal(aid)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an UNDER_REVIEW appeal can be adjudicated")
    adjudicate_appeal(rec, decision, note)
    return success_object(ser_appeal(rec))
