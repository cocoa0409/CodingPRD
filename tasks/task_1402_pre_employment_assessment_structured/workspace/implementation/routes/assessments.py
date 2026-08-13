"""Candidate assessments: lifecycle, feedback, accommodations, purge events
(PRD §3.5, §3.8, §3.9)."""
from datetime import timedelta

import db
import serializers
import util
from errors import (api_err, err_invalid_request, err_not_found, err_ownership)
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import (bump, filter_params, new_id, next_seq, paginate, parse_dt,
                  req_enum, req_int, req_string, sort_records)

bp = Blueprint("assessments", __name__)

READ_ROLES = ["HiringManager", "TalentAssessmentAdmin", "ComplianceOfficer",
              "DecisionOfficer", "Candidate"]
REQUEST_TYPES = ["EXTENDED_TIME", "ALTERNATE_FORMAT", "SCREEN_READER", "OTHER"]


def _get_assessment_or_404(aid):
    a = db.stores["assessments"].get(aid)
    if a is None:
        raise err_not_found("CandidateAssessment not found")
    return a


def _own_assessment_cycle(ctx, a):
    cyc = db.stores["cycles"].get(a["cycle_id"])
    req = db.stores["requisitions"].get(cyc["requisition_id"]) if cyc else None
    if req is None or req["hiring_manager_id"] != ctx.user_id:
        raise err_ownership("Only the owning HiringManager may operate on this assessment")
    return cyc, req


def _posture_gate(cyc, admitted):
    if cyc["posture"] == "FROZEN":
        raise api_err("ERR_CYCLE_FROZEN", "Cycle is FROZEN")
    if cyc["posture"] not in admitted:
        raise api_err("ERR_CYCLE_NOT_ACTIVE", "Cycle posture does not admit this operation")


def _effective_window(cyc, a):
    """Closed interval [window_start, window_end + accommodation_extension_days]."""
    start = cyc["administration_window_start"]
    end = cyc["administration_window_end"] + timedelta(days=a["accommodation_extension_days"])
    return start, end


@bp.get("/talent/assessments")
def list_assessments():
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    filters = filter_params(["cycle_id", "candidate_id", "admin_status"])
    # Entity-backed scoping: Candidate must pass candidate_id == X-User-ID
    if ctx.role == "Candidate":
        if filters.get("candidate_id") != ctx.user_id:
            raise err_ownership("Candidate must filter assessments by own candidate_id")
    recs = []
    for a in sort_records(list(db.stores["assessments"].values())):
        if "cycle_id" in filters and a["cycle_id"] != filters["cycle_id"]:
            continue
        if "candidate_id" in filters and a["candidate_id"] != filters["candidate_id"]:
            continue
        if "admin_status" in filters and a["admin_status"] != filters["admin_status"]:
            continue
        recs.append(serializers.assessment(a))
    return paginate(recs)


@bp.get("/talent/assessments/<aid>")
def get_assessment(aid):
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    a = _get_assessment_or_404(aid)
    if ctx.role == "Candidate" and a["candidate_id"] != ctx.user_id:
        raise err_ownership("Candidate may only read own assessments")
    return success_object(serializers.assessment(a))


@bp.post("/talent/assessments/<aid>/schedule")
def schedule_assessment(aid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    a = _get_assessment_or_404(aid)
    body = util.get_body()
    cyc, _req = _own_assessment_cycle(ctx, a)
    if a["admin_status"] != "INVITED":
        raise api_err("ERR_INVALID_STATE", "Assessment must be INVITED to schedule")
    _posture_gate(cyc, ("ACTIVE",))
    scheduled_for = parse_dt(body.get("scheduled_for"), "scheduled_for")
    a["scheduled_for"] = scheduled_for
    a["admin_status"] = "SCHEDULED"
    bump(a)
    return success_object(serializers.assessment(a))


@bp.post("/talent/assessments/<aid>/start")
def start_assessment(aid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    a = _get_assessment_or_404(aid)
    util.get_body()
    cyc, _req = _own_assessment_cycle(ctx, a)
    if a["admin_status"] != "SCHEDULED":
        raise api_err("ERR_INVALID_STATE", "Assessment must be SCHEDULED to start")
    _posture_gate(cyc, ("ACTIVE",))
    now = db.get_now()
    start, end = _effective_window(cyc, a)
    if not (start <= now <= end):
        raise api_err("ERR_OUTSIDE_ADMINISTRATION_WINDOW",
                      "Start is outside the effective administration window")
    a["started_at"] = now
    a["admin_status"] = "IN_PROGRESS"
    bump(a)
    return success_object(serializers.assessment(a))


@bp.post("/talent/assessments/<aid>/complete")
def complete_assessment(aid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    a = _get_assessment_or_404(aid)
    body = util.get_body()
    cyc, _req = _own_assessment_cycle(ctx, a)
    if a["admin_status"] != "IN_PROGRESS":
        raise api_err("ERR_INVALID_STATE", "Assessment must be IN_PROGRESS to complete")
    _posture_gate(cyc, ("ACTIVE",))
    # Temporal gate (tier 11) before the raw-score range check (tier 16)
    now = db.get_now()
    start, end = _effective_window(cyc, a)
    if not (start <= now <= end):
        raise api_err("ERR_OUTSIDE_ADMINISTRATION_WINDOW",
                      "Completion is outside the effective administration window")
    raw_score = body.get("raw_score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        raise err_invalid_request("raw_score is required and must be a number")
    instrument = db.stores["instruments"].get(cyc["instrument_id"])
    if raw_score < 0 or raw_score > instrument["max_score"]:
        raise api_err("ERR_SCORE_OUT_OF_RANGE",
                      "raw_score must lie between 0 and the instrument max_score")
    a["raw_score"] = raw_score
    a["completed_at"] = now
    a["admin_status"] = "COMPLETED"
    core.compute_composite(a)
    bump(a)
    return success_object(serializers.assessment(a))


@bp.post("/talent/assessments/<aid>/mark-no-show")
def mark_no_show(aid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    a = _get_assessment_or_404(aid)
    util.get_body()
    cyc, _req = _own_assessment_cycle(ctx, a)
    if a["admin_status"] != "SCHEDULED":
        raise api_err("ERR_INVALID_STATE", "Assessment must be SCHEDULED to mark no-show")
    now = db.get_now()
    if a["scheduled_for"] is None or not (now > a["scheduled_for"]):
        raise api_err("ERR_INVALID_STATE",
                      "No-show requires now strictly after scheduled_for")
    a["admin_status"] = "NO_SHOW"
    if a["feedback_status"] == "NOT_SENT":
        a["feedback_status"] = "NOT_APPLICABLE"
    bump(a)
    return success_object(serializers.assessment(a))


@bp.post("/talent/assessments/<aid>/cancel")
def cancel_assessment(aid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager", "Candidate"])
    a = _get_assessment_or_404(aid)
    util.get_body()
    if ctx.role == "Candidate":
        if a["candidate_id"] != ctx.user_id:
            raise err_ownership("Candidate may only cancel own assessment")
    else:
        _own_assessment_cycle(ctx, a)
    if a["admin_status"] not in core.CANCELLABLE_ADMIN:
        raise api_err("ERR_INVALID_STATE",
                      "Assessment cannot be cancelled from its current state")
    reason = "CANDIDATE_WITHDRAWN" if ctx.role == "Candidate" else "MANUAL"
    core.cancel_assessment(a, reason)
    return success_object(serializers.assessment(a))


@bp.post("/talent/assessments/<aid>/reschedule")
def reschedule_assessment(aid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    a = _get_assessment_or_404(aid)
    body = util.get_body()
    cyc, _req = _own_assessment_cycle(ctx, a)
    if a["admin_status"] != "ACCOMMODATION_HOLD":
        raise api_err("ERR_INVALID_STATE",
                      "Assessment must be ACCOMMODATION_HOLD to reschedule")
    _posture_gate(cyc, ("ACTIVE",))
    scheduled_for = parse_dt(body.get("scheduled_for"), "scheduled_for")
    a["scheduled_for"] = scheduled_for
    a["admin_status"] = "SCHEDULED"
    bump(a)
    return success_object(serializers.assessment(a))


@bp.post("/talent/assessments/<aid>/feedback")
def send_feedback(aid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    a = _get_assessment_or_404(aid)
    body = util.get_body()
    cyc, _req = _own_assessment_cycle(ctx, a)
    # Precondition order per PRD §3.8: COMPLETED -> retention gate ->
    # feedback_text length -> duplicate -> decision finalized.
    if a["admin_status"] != "COMPLETED":
        raise api_err("ERR_ASSESSMENT_NOT_COMPLETED",
                      "Feedback requires a COMPLETED assessment")
    now = db.get_now()
    if a["retention_expires_at"] is not None and now > a["retention_expires_at"]:
        raise api_err("ERR_RETENTION_EXPIRED", "Retention window has expired")
    text = body.get("feedback_text")
    if not isinstance(text, str):
        raise err_invalid_request("feedback_text is required")
    if len(text) < 20:
        raise api_err("ERR_FEEDBACK_TEXT_TOO_SHORT",
                      "feedback_text must be at least 20 characters")
    if a["feedback_status"] != "NOT_SENT":
        raise api_err("ERR_FEEDBACK_ALREADY_SENT", "Feedback was already sent")
    if core.finalized_decision(a["cycle_id"], a["candidate_id"]) is None:
        raise api_err("ERR_DECISION_NOT_FINALIZED",
                      "A FINALIZED hiring decision is required before feedback")
    a["feedback_status"] = "SENT"
    bump(a)
    return success_object(serializers.assessment(a))


@bp.post("/talent/assessments/<aid>/accommodation-requests")
def create_accommodation(aid):
    ctx = authenticate()
    require_roles(ctx, ["Candidate"])
    a = _get_assessment_or_404(aid)
    if a["candidate_id"] != ctx.user_id:
        raise err_ownership("Accommodation requests belong to the candidate")
    body = util.get_body()
    # Uniqueness (tier 10) precedes field-shape validation (tier 16)
    for ar in db.stores["accommodation_requests"].values():
        if ar["candidate_assessment_id"] == aid and ar["status"] == "PENDING":
            raise api_err("ERR_PENDING_ACCOMMODATION_EXISTS",
                          "Assessment already has a PENDING accommodation request")
    request_type = req_enum(body, "request_type", REQUEST_TYPES)
    justification = req_string(body, "justification", min_len=20)
    requested_days = req_int(body, "requested_extension_days", lo=1, hi=30)
    now = db.get_now()
    rec = {
        "id": new_id(),
        "candidate_assessment_id": aid,
        "request_type": request_type,
        "justification": justification,
        "requested_extension_days": requested_days,
        "status": "PENDING",
        "approved_extension_days": None,
        "decision_note": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["accommodation_requests"][rec["id"]] = rec
    return success_object(serializers.accommodation(rec), 201)


@bp.get("/talent/assessments/<aid>/accommodation-requests")
def list_accommodations(aid):
    ctx = authenticate()
    require_roles(ctx, ["Candidate", "ComplianceOfficer", "HiringManager",
                        "TalentAssessmentAdmin"])
    a = _get_assessment_or_404(aid)
    if ctx.role == "Candidate" and a["candidate_id"] != ctx.user_id:
        raise err_ownership("Candidate may only list own accommodation requests")
    recs = [serializers.accommodation(r) for r in sort_records(
        [r for r in db.stores["accommodation_requests"].values()
         if r["candidate_assessment_id"] == aid])]
    return paginate(recs)


@bp.get("/talent/assessments/<aid>/purge-events")
def list_purge_events(aid):
    ctx = authenticate()
    require_roles(ctx, ["ComplianceOfficer", "TalentAssessmentAdmin"])
    _get_assessment_or_404(aid)
    recs = [serializers.purge_event(e) for e in sort_records(
        [e for e in db.stores["purge_events"].values()
         if e["candidate_assessment_id"] == aid])]
    return paginate(recs)
