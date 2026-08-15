"""Exam session and candidate endpoints (PRD §3.7), including the check-in /
result-recording segregation of duties and the license upgrade on a pass."""
from datetime import timedelta

from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_CANDIDATES_PENDING, ERR_CANDIDATE_NOT_CHECKED_IN,
    ERR_DUPLICATE_CANDIDATE_FRN, ERR_INVALID_STATE, ERR_SESSION_FULL,
    ERR_SOD_EXAM_GRADING, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    LICENSE_CLASSES, LICENSE_ORDER, as_dt, as_enum, as_int, as_str, bad_request,
    body_json, need, opt, reject_unknown_fields,
)

bp = Blueprint("exams", __name__)

SESSION_STATUSES = {"SCHEDULED", "IN_PROGRESS", "CLOSED", "CANCELLED"}
LIAISON = {"ExamLiaison"}
READ_ROLES = {"ClubAdmin", "ExamLiaison"}


def _auth(allowed):
    user_id, role = auth_context()
    require_role(role, allowed)
    return user_id, role


@bp.post("/exam-sessions")
def create_session():
    _auth(LIAISON)
    body = body_json(request)
    reject_unknown_fields(body, {"location", "scheduled_at", "max_candidates"})
    location = as_str(need(body, "location"), "location")
    scheduled_at = as_dt(need(body, "scheduled_at"), "scheduled_at")
    max_candidates = as_int(need(body, "max_candidates"), "max_candidates")
    if max_candidates <= 0:
        bad_request("max_candidates must be > 0")
    session = {
        "location": location,
        "scheduled_at": scheduled_at,
        "max_candidates": max_candidates,
        "status": "SCHEDULED",
    }
    svc.stamp_new(session)
    db.STORE["exam_sessions"][session["id"]] = session
    return success(svc.ser_session(session), "object", 201)


@bp.get("/exam-sessions")
def list_sessions():
    _auth(READ_ROLES)
    status = request.args.get("status")
    items = [svc.ser_session(s) for s in svc.sorted_records("exam_sessions")
             if status is None or s["status"] == status]
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/exam-sessions/<sid>")
def get_session(sid):
    _auth(READ_ROLES)
    return success(svc.ser_session(svc.get_session(sid)), "object", 200)


@bp.post("/exam-sessions/<sid>/set-status")
def set_session_status(sid):
    _auth(LIAISON)
    session = svc.get_session(sid)
    body = body_json(request)
    reject_unknown_fields(body, {"to"})
    to = as_enum(need(body, "to"), "to", SESSION_STATUSES)
    current = session["status"]
    if to == "IN_PROGRESS":
        if current != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot open a session in status %s" % current)
        if db.now() < session["scheduled_at"]:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "session may open only at or after scheduled_at")
        session["status"] = "IN_PROGRESS"
        svc.touch(session)
    elif to == "CLOSED":
        if current != "IN_PROGRESS":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot close a session in status %s" % current)
        pending = any(
            c["session_id"] == session["id"]
            and c["status"] not in svc.CANDIDATE_TERMINAL
            for c in db.STORE["exam_candidates"].values()
        )
        if pending:
            raise ApiError(ERR_CANDIDATES_PENDING, 409,
                           "candidates remain in a non-terminal state")
        session["status"] = "CLOSED"
        svc.touch(session)
    elif to == "CANCELLED":
        if current not in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot cancel a session in status %s" % current)
        session["status"] = "CANCELLED"
        svc.touch(session)
        # Cascade: non-terminal candidates become CANCELLED.
        for c in svc.sorted_records("exam_candidates"):
            if (c["session_id"] == session["id"]
                    and c["status"] in ("REGISTERED", "CHECKED_IN")):
                c["status"] = "CANCELLED"
                svc.touch(c)
    else:  # SCHEDULED is never a manual target
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot move a session from %s to %s" % (current, to))
    return success(svc.ser_session(session), "object", 200)


# ---------------------------------------------------------------------------
# Exam candidates
# ---------------------------------------------------------------------------

@bp.post("/exam-candidates")
def create_candidate():
    _auth(LIAISON)
    body = body_json(request)
    reject_unknown_fields(body, {"session_id", "candidate_name", "frn",
                                 "element", "member_id"})
    session_id = as_str(need(body, "session_id"), "session_id")
    session = svc.get_session(session_id)  # body FK existence
    candidate_name = as_str(need(body, "candidate_name"), "candidate_name")
    frn = as_str(need(body, "frn"), "frn")
    element = as_enum(need(body, "element"), "element", LICENSE_CLASSES)
    member_id = opt(body, "member_id")
    if member_id is not None:
        member_id = as_str(member_id, "member_id")
        svc.get_member(member_id)  # optional body FK existence
    if session["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "registration is open only while the session is SCHEDULED")
    for c in db.STORE["exam_candidates"].values():
        if c["session_id"] == session["id"] and c["frn"] == frn:
            raise ApiError(ERR_DUPLICATE_CANDIDATE_FRN, 409,
                           "FRN already registered within this session")
    if svc.session_registered_count(session) >= session["max_candidates"]:
        raise ApiError(ERR_SESSION_FULL, 409,
                       "session is at max_candidates")
    cand = {
        "session_id": session["id"],
        "candidate_name": candidate_name,
        "frn": frn,
        "element": element,
        "member_id": member_id,
        "status": "REGISTERED",
        "checked_in_by_member_id": None,
        "score_percent": None,
    }
    svc.stamp_new(cand)
    db.STORE["exam_candidates"][cand["id"]] = cand
    return success(svc.ser_candidate(cand), "object", 201)


@bp.get("/exam-candidates")
def list_candidates():
    _auth(READ_ROLES)
    session_id = request.args.get("session_id")
    member_id = request.args.get("member_id")
    checked_in_by = request.args.get("checked_in_by_member_id")
    status = request.args.get("status")
    items = []
    for c in svc.sorted_records("exam_candidates"):
        if session_id is not None and c["session_id"] != session_id:
            continue
        if member_id is not None and c["member_id"] != member_id:
            continue
        if checked_in_by is not None and c["checked_in_by_member_id"] != checked_in_by:
            continue
        if status is not None and c["status"] != status:
            continue
        items.append(svc.ser_candidate(c))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/exam-candidates/<cid>")
def get_candidate(cid):
    _auth(READ_ROLES)
    return success(svc.ser_candidate(svc.get_candidate(cid)), "object", 200)


@bp.post("/exam-candidates/<cid>/check-in")
def check_in_candidate(cid):
    user_id, role = _auth(LIAISON)
    cand = svc.get_candidate(cid)
    body = body_json(request)
    reject_unknown_fields(body, set())
    session = svc.get_session(cand["session_id"])
    if session["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "check-in requires the session to be IN_PROGRESS")
    if cand["status"] != "REGISTERED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot check in a candidate in status %s" % cand["status"])
    cand["status"] = "CHECKED_IN"
    cand["checked_in_by_member_id"] = user_id
    svc.touch(cand)
    return success(svc.ser_candidate(cand), "object", 200)


@bp.post("/exam-candidates/<cid>/record-result")
def record_result(cid):
    user_id, role = _auth(LIAISON)
    cand = svc.get_candidate(cid)
    body = body_json(request)
    reject_unknown_fields(body, {"score_percent"})
    score_percent = as_int(need(body, "score_percent"), "score_percent")
    if score_percent < 0 or score_percent > 100:
        bad_request("score_percent must be in 0..100")
    session = svc.get_session(cand["session_id"])
    if session["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "result recording requires the session to be IN_PROGRESS")
    if cand["status"] != "CHECKED_IN":
        raise ApiError(ERR_CANDIDATE_NOT_CHECKED_IN, 409,
                       "record-result requires candidate status CHECKED_IN")
    # Segregation of duties: recorder != the member who checked the candidate in.
    if user_id == cand["checked_in_by_member_id"]:
        raise ApiError(ERR_SOD_EXAM_GRADING, 403,
                       "result recorder must differ from checked_in_by_member_id")
    passed = score_percent >= svc.EXAM_PASS_PERCENT
    cand["status"] = "PASSED" if passed else "FAILED"
    cand["score_percent"] = score_percent
    svc.touch(cand)
    if passed and cand["member_id"] is not None:
        member = svc.get_member(cand["member_id"])
        if LICENSE_ORDER[cand["element"]] > LICENSE_ORDER[member["license_class"]]:
            member["license_class"] = cand["element"]
        member["license_expires_at"] = (
            db.now() + timedelta(days=svc.EXAM_PASS_LICENSE_DAYS))
        svc.touch(member)
    return success(svc.ser_candidate(cand), "object", 200)


@bp.post("/exam-candidates/<cid>/mark-no-show")
def mark_no_show(cid):
    _auth(LIAISON)
    cand = svc.get_candidate(cid)
    body = body_json(request)
    reject_unknown_fields(body, set())
    session = svc.get_session(cand["session_id"])
    if session["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "mark-no-show requires the session to be IN_PROGRESS")
    if cand["status"] != "REGISTERED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot no-show a candidate in status %s" % cand["status"])
    cand["status"] = "NO_SHOW"
    svc.touch(cand)
    return success(svc.ser_candidate(cand), "object", 200)
