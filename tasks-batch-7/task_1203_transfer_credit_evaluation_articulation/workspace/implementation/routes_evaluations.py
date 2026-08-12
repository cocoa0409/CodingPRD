"""Evaluation and evaluation line-item routes."""
from decimal import Decimal

from flask import Blueprint, request

import db
from db import touch
from errors import (ApiError, ERR_AGREEMENT_NOT_ACTIVE, ERR_COURSE_INACTIVE,
                    ERR_DUPLICATE_EVALUATION, ERR_EVALUATION_NOT_IN_REVIEW,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
                    ERR_NOT_RESOURCE_OWNER, ERR_POSTER_IS_EVALUATOR,
                    ERR_TRANSCRIPT_NOT_VERIFIED, ERR_TRANSCRIPT_STUDENT_MISMATCH,
                    ERR_UNRESOLVED_LINE_ITEMS)
from middleware import ANY, current_user, require_roles
from response import get_body, paginate, success_object
from services import (evaluation_of_line, final_credit_award,
                      intake_evaluation, lines_of_evaluation, reopen_evaluation,
                      recompute_evaluation, run_post_waterfall, ser_evaluation,
                      ser_line, student_of_evaluation)
from util import opt_str, req_str

bp = Blueprint("evaluations", __name__)

EVALUATOR = ("TransferEvaluator",)


def _get_evaluation(eid):
    rec = db.evaluations.get(eid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       f"TransferCreditEvaluation not found: {eid}")
    return rec


def _get_line(lid):
    rec = db.lines.get(lid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"EvaluationLineItem not found: {lid}")
    return rec


def _check_eval_ownership(ev):
    uid, role = current_user()
    if role == "Student" and ev["student_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Students may only access their own records")


def _partner_credit_system(ev):
    tr = db.transcripts.get(ev["transcript_id"])
    partner = db.partners.get(tr["partner_institution_id"]) if tr else None
    return partner["credit_system"] if partner else "SEMESTER"


# ---------------------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------------------

@bp.route("/api/transfer-credit-evaluations", methods=["POST"])
@require_roles(*EVALUATOR)
def create_evaluation():
    body = get_body()
    student_id = req_str(body, "student_id")
    transcript_id = req_str(body, "transcript_id")
    # Body FK existence (priority 4)
    student = db.students.get(student_id)
    if student is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"TransferStudent not found: {student_id}")
    transcript = db.transcripts.get(transcript_id)
    if transcript is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"Transcript not found: {transcript_id}")
    # One evaluation per transcript (priority 7.5): deliberately BEFORE the
    # transcript-state check so the duplicate path stays observable after the
    # transcript has moved to EXTRACTED.
    for ev in db.evaluations.values():
        if ev["transcript_id"] == transcript_id:
            raise ApiError(ERR_DUPLICATE_EVALUATION, 409,
                           "An evaluation already exists for this transcript")
    # Transcript state (priority 8)
    if transcript["status"] != "VERIFIED":
        raise ApiError(ERR_TRANSCRIPT_NOT_VERIFIED, 409,
                       "Transcript must be VERIFIED to create an evaluation")
    # Student match (priority 9)
    if transcript["student_id"] != student_id:
        raise ApiError(ERR_TRANSCRIPT_STUDENT_MISMATCH, 422,
                       "student_id does not match the transcript's student")
    ev = db.create_rec(db.evaluations, {
        "student_id": student_id, "transcript_id": transcript_id,
        "status": "DRAFT",
        "provisional_credits_total": Decimal("0"),
        "awarded_credits_total": Decimal("0"),
        "applied_credits_total": Decimal("0"),
        "open_line_count": 0,
        "evaluated_by_id": None, "posted_by_id": None, "posted_at": None,
        "reopen_reason": None,
    })
    # Transcript VERIFIED -> EXTRACTED (system transition)
    transcript["status"] = "EXTRACTED"
    touch(transcript)
    # Line intake: grade conversion + auto-match + provisional credits
    intake_evaluation(ev, transcript, student)
    return success_object(ser_evaluation(ev), 201)


@bp.route("/api/transfer-credit-evaluations", methods=["GET"])
@require_roles(*ANY)
def list_evaluations():
    uid, role = current_user()
    student_id = request.args.get("student_id")
    transcript_id = request.args.get("transcript_id")
    status = request.args.get("status")
    recs = list(db.evaluations.values())
    if role == "Student":
        recs = [e for e in recs if e["student_id"] == uid]
    if student_id is not None:
        recs = [e for e in recs if e["student_id"] == student_id]
    if transcript_id is not None:
        recs = [e for e in recs if e["transcript_id"] == transcript_id]
    if status is not None:
        recs = [e for e in recs if e["status"] == status]
    return paginate(recs, ser_evaluation)


@bp.route("/api/transfer-credit-evaluations/<eid>", methods=["GET"])
@require_roles(*ANY)
def get_evaluation(eid):
    rec = _get_evaluation(eid)
    _check_eval_ownership(rec)
    return success_object(ser_evaluation(rec))


@bp.route("/api/transfer-credit-evaluations/<eid>/line-items", methods=["GET"])
@require_roles(*ANY)
def list_evaluation_lines(eid):
    rec = _get_evaluation(eid)
    _check_eval_ownership(rec)
    lines = lines_of_evaluation(eid)
    # An unparameterized read returns the evaluation's full line set; explicit
    # limit/offset opt into pagination.
    if "limit" not in request.args and "offset" not in request.args:
        from response import success_list
        return success_list([ser_line(l) for l in lines], len(lines), 0, len(lines))
    return paginate(lines, ser_line)


@bp.route("/api/transfer-credit-evaluations/<eid>/start-review", methods=["POST"])
@require_roles(*EVALUATOR)
def start_review(eid):
    ev = _get_evaluation(eid)
    if ev["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT evaluation can move to IN_REVIEW")
    ev["status"] = "IN_REVIEW"
    touch(ev)
    return success_object(ser_evaluation(ev))


@bp.route("/api/transfer-credit-evaluations/<eid>/finalize", methods=["POST"])
@require_roles(*EVALUATOR)
def finalize(eid):
    ev = _get_evaluation(eid)
    if ev["status"] != "IN_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an IN_REVIEW evaluation can be finalized")
    uid, _ = current_user()
    ev_lines = lines_of_evaluation(eid)
    if any(l["status"] not in ("ADOPTED", "DENIED") for l in ev_lines):
        raise ApiError(ERR_UNRESOLVED_LINE_ITEMS, 409,
                       "All line items must be ADOPTED or DENIED before finalize")
    credit_system = _partner_credit_system(ev)
    total = Decimal("0")
    for line in ev_lines:
        if line["status"] != "ADOPTED":
            continue
        course = db.courses.get(line["internal_course_id"])
        cap = course["credit_hours"] if course else Decimal("0")
        # Final variant recompute at finalize
        line["awarded_credits"] = final_credit_award(
            line["external_credit_hours"], credit_system, cap)
        touch(line)
        total += line["awarded_credits"]
    ev["awarded_credits_total"] = total
    ev["evaluated_by_id"] = uid
    ev["status"] = "EVALUATED"
    touch(ev)
    return success_object(ser_evaluation(ev))


@bp.route("/api/transfer-credit-evaluations/<eid>/post", methods=["POST"])
@require_roles(*EVALUATOR)
def post(eid):
    ev = _get_evaluation(eid)
    if ev["status"] != "EVALUATED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an EVALUATED evaluation can be posted")
    # Every ADOPTED line's equivalency agreement must be ACTIVE (priority 13)
    for line in lines_of_evaluation(eid):
        if line["status"] != "ADOPTED":
            continue
        eq_id = line.get("equivalency_id")
        if not eq_id:
            continue
        eq = db.equivalencies.get(eq_id)
        ag = db.agreements.get(eq["agreement_id"]) if eq else None
        if ag is None or ag["status"] != "ACTIVE":
            raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, 409,
                           "An ADOPTED line's equivalency belongs to a non-ACTIVE agreement")
    # Segregation of duties: the last gate evaluated (priority 27)
    uid, _ = current_user()
    if uid == ev.get("evaluated_by_id"):
        raise ApiError(ERR_POSTER_IS_EVALUATOR, 403,
                       "The posting evaluator must differ from evaluated_by_id")
    student = student_of_evaluation(ev)
    run_post_waterfall(ev, student, uid)
    return success_object(ser_evaluation(ev))


@bp.route("/api/transfer-credit-evaluations/<eid>/reopen", methods=["POST"])
@require_roles(*EVALUATOR)
def reopen(eid):
    body = get_body()
    reason = req_str(body, "reason")
    ev = _get_evaluation(eid)
    if ev["status"] != "POSTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a POSTED evaluation can be reopened")
    reopen_evaluation(ev, reason)
    return success_object(ser_evaluation(ev))


# ---------------------------------------------------------------------------
# Evaluation line items
# ---------------------------------------------------------------------------

@bp.route("/api/evaluation-line-items", methods=["GET"])
@require_roles(*ANY)
def list_lines():
    uid, role = current_user()
    eq_id = request.args.get("equivalency_id")
    course_id = request.args.get("internal_course_id")
    status = request.args.get("status")
    ev_id = request.args.get("evaluation_id")
    recs = list(db.lines.values())
    if role == "Student":
        recs = [l for l in recs
                if (evaluation_of_line(l) or {}).get("student_id") == uid]
    if eq_id is not None:
        recs = [l for l in recs if l.get("equivalency_id") == eq_id]
    if course_id is not None:
        recs = [l for l in recs if l.get("internal_course_id") == course_id]
    if status is not None:
        recs = [l for l in recs if l["status"] == status]
    if ev_id is not None:
        recs = [l for l in recs if l["evaluation_id"] == ev_id]
    return paginate(recs, ser_line)


@bp.route("/api/evaluation-line-items/<lid>", methods=["GET"])
@require_roles(*ANY)
def get_line(lid):
    rec = _get_line(lid)
    uid, role = current_user()
    if role == "Student":
        ev = evaluation_of_line(rec)
        if ev is None or ev["student_id"] != uid:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                           "Students may only access their own records")
    return success_object(ser_line(rec))


def _adopt_deny_prechecks(line):
    """Line from-state (priority 7) before evaluation IN_REVIEW (priority 10)."""
    if line["status"] not in ("AUTO_MATCHED", "PETITION_REQUIRED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only AUTO_MATCHED or PETITION_REQUIRED lines can be resolved")
    ev = evaluation_of_line(line)
    if ev is None or ev["status"] != "IN_REVIEW":
        raise ApiError(ERR_EVALUATION_NOT_IN_REVIEW, 409,
                       "The enclosing evaluation must be IN_REVIEW")
    return ev


@bp.route("/api/evaluation-line-items/<lid>/adopt", methods=["POST"])
@require_roles(*EVALUATOR)
def adopt_line(lid):
    body = get_body()
    course_id = body.get("internal_course_id")
    if course_id is not None and not isinstance(course_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "internal_course_id must be a string")
    # Path id existence, then body FK existence (priority 4)
    line = _get_line(lid)
    course = None
    if course_id is not None:
        course = db.courses.get(course_id)
        if course is None:
            raise ApiError(ERR_NOT_FOUND, 404,
                           f"InternalCourse not found: {course_id}")
    ev = _adopt_deny_prechecks(line)
    credit_system = _partner_credit_system(ev)
    if line["status"] == "AUTO_MATCHED":
        # Bare confirmation of the auto-match
        line["resolution"] = "AUTO_EQUIVALENCY"
        target = db.courses.get(line["internal_course_id"])
    else:
        # PETITION_REQUIRED manual override: internal_course_id required
        if course_id is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "internal_course_id is required to adopt a PETITION_REQUIRED line")
        if not course["is_active"]:
            raise ApiError(ERR_COURSE_INACTIVE, 422,
                           "Referenced internal course is archived")
        line["resolution"] = "MANUAL_OVERRIDE"
        line["internal_course_id"] = course_id
        target = course
    line["awarded_credits"] = final_credit_award(
        line["external_credit_hours"], credit_system, target["credit_hours"])
    line["status"] = "ADOPTED"
    touch(line)
    recompute_evaluation(ev)
    return success_object(ser_line(line))


@bp.route("/api/evaluation-line-items/<lid>/deny", methods=["POST"])
@require_roles(*EVALUATOR)
def deny_line(lid):
    body = get_body()
    reason = req_str(body, "reason")
    line = _get_line(lid)
    ev = _adopt_deny_prechecks(line)
    line["status"] = "DENIED"
    line["denial_reason"] = reason
    line["provisional_credits"] = None
    touch(line)
    recompute_evaluation(ev)
    return success_object(ser_line(line))
