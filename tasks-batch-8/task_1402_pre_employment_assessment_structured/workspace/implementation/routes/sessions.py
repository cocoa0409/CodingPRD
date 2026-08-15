"""Interview sessions: booking gauntlet, complete, cancel (PRD §3.6), and
scorecard creation nested under a session."""
from datetime import timedelta

import db
import serializers
import util
from errors import (api_err, err_invalid_request, err_not_found, err_ownership,
                    err_ref_not_found)
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import (bump, filter_params, new_id, next_seq, paginate, parse_dt,
                  req_enum, sort_records)

bp = Blueprint("sessions", __name__)

READ_ROLES = ["TalentAssessmentAdmin", "HiringManager", "Interviewer",
              "ComplianceOfficer", "DecisionOfficer", "Candidate"]
RECOMMENDATIONS = ["STRONG_YES", "YES", "NO", "STRONG_NO"]


def _get_session_or_404(sid):
    s = db.stores["sessions"].get(sid)
    if s is None:
        raise err_not_found("InterviewSession not found")
    return s


def _cycle_of(s):
    return db.stores["cycles"].get(s["cycle_id"])


def _own_session_cycle(ctx, s):
    cyc = _cycle_of(s)
    req = db.stores["requisitions"].get(cyc["requisition_id"]) if cyc else None
    if req is None or req["hiring_manager_id"] != ctx.user_id:
        raise err_ownership("Only the owning HiringManager may operate on this session")
    return cyc


@bp.get("/talent/sessions")
def list_sessions():
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    filters = filter_params(["cycle_id", "candidate_id", "interviewer_id", "guide_id", "status"])
    if ctx.role == "Interviewer":
        if "interviewer_id" in filters and filters["interviewer_id"] != ctx.user_id:
            raise err_ownership("Interviewer must filter by own interviewer_id")
    if ctx.role == "Candidate":
        if "candidate_id" in filters and filters["candidate_id"] != ctx.user_id:
            raise err_ownership("Candidate must filter by own candidate_id")
    recs = []
    for s in sort_records(list(db.stores["sessions"].values())):
        if "cycle_id" in filters and s["cycle_id"] != filters["cycle_id"]:
            continue
        if "candidate_id" in filters and s["candidate_id"] != filters["candidate_id"]:
            continue
        if "interviewer_id" in filters and s["interviewer_id"] != filters["interviewer_id"]:
            continue
        if "guide_id" in filters and s["guide_id"] != filters["guide_id"]:
            continue
        if "status" in filters and s["status"] != filters["status"]:
            continue
        recs.append(serializers.session(s))
    return paginate(recs)


@bp.get("/talent/sessions/<sid>")
def get_session(sid):
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    s = _get_session_or_404(sid)
    if ctx.role == "Interviewer" and s["interviewer_id"] != ctx.user_id:
        raise err_ownership("Interviewer may only read own sessions")
    if ctx.role == "Candidate" and s["candidate_id"] != ctx.user_id:
        raise err_ownership("Candidate may only read own sessions")
    return success_object(serializers.session(s))


@bp.post("/talent/cycles/<cid>/sessions")
def create_session(cid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    cyc = db.stores["cycles"].get(cid)
    if cyc is None:
        raise err_not_found("AssessmentCycle not found")
    body = util.get_body()
    # Body FK resolution left-to-right: candidate_id, interviewer_id, guide_id
    candidate_id = body.get("candidate_id")
    if not isinstance(candidate_id, str):
        raise err_invalid_request("candidate_id is required")
    candidate = db.stores["candidates"].get(candidate_id)
    if candidate is None:
        raise err_ref_not_found("candidate_id does not resolve")
    interviewer_id = body.get("interviewer_id")
    if not isinstance(interviewer_id, str):
        raise err_invalid_request("interviewer_id is required")
    interviewer = db.stores["interviewers"].get(interviewer_id)
    if interviewer is None:
        raise err_ref_not_found("interviewer_id does not resolve")
    guide_id = body.get("guide_id")
    if not isinstance(guide_id, str):
        raise err_invalid_request("guide_id is required")
    guide = db.stores["guides"].get(guide_id)
    if guide is None:
        raise err_ref_not_found("guide_id does not resolve")
    # Ownership (tier 5)
    req = db.stores["requisitions"].get(cyc["requisition_id"])
    if req is None or req["hiring_manager_id"] != ctx.user_id:
        raise err_ownership("Only the owning HiringManager may book sessions")
    # Posture gate (tier 7) then assessment completion (tier 7)
    if cyc["posture"] == "FROZEN":
        raise api_err("ERR_CYCLE_FROZEN", "Cycle is FROZEN")
    if cyc["posture"] != "ACTIVE":
        raise api_err("ERR_CYCLE_NOT_ACTIVE", "Cycle must be ACTIVE")
    assessment = None
    for a in db.stores["assessments"].values():
        if a["cycle_id"] == cid and a["candidate_id"] == candidate_id:
            assessment = a
            break
    if assessment is None or assessment["admin_status"] != "COMPLETED":
        raise api_err("ERR_ASSESSMENT_NOT_COMPLETED",
                      "The candidate's assessment in this cycle must be COMPLETED")
    # Safety gate: CALIBRATED calibration for the cycle's pinned guide (tier 9)
    calibrated = any(
        rec["interviewer_id"] == interviewer_id
        and rec["guide_id"] == cyc["guide_id"]
        and rec["status"] == "CALIBRATED"
        for rec in db.stores["calibrations"].values()
    )
    if not calibrated:
        raise api_err("ERR_INTERVIEWER_NOT_CALIBRATED",
                      "Interviewer must be CALIBRATED for the cycle's pinned guide")
    # Constraint tier: duration
    scheduled_start = parse_dt(body.get("scheduled_start"), "scheduled_start")
    scheduled_end = parse_dt(body.get("scheduled_end"), "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise api_err("ERR_SESSION_DURATION_INVALID",
                      "scheduled_end must be strictly after scheduled_start")
    duration_min = (scheduled_end - scheduled_start).total_seconds() / 60
    if duration_min < 15 or duration_min > 240:
        raise api_err("ERR_SESSION_DURATION_INVALID",
                      "Session duration must be 15..240 minutes")
    # Double-booking, half-open intervals [start, end)
    for s in db.stores["sessions"].values():
        if s["interviewer_id"] != interviewer_id:
            continue
        if s["status"] not in ("SCHEDULED", "COMPLETED", "SCORED"):
            continue
        if scheduled_start < s["scheduled_end"] and scheduled_end > s["scheduled_start"]:
            raise api_err("ERR_INTERVIEWER_DOUBLE_BOOKED",
                          "Interviewer has an overlapping session")
    # Daily capacity (aggregate over the UTC calendar day of scheduled_start)
    day = scheduled_start.date()
    day_count = 0
    for s in db.stores["sessions"].values():
        if s["cycle_id"] != cid:
            continue
        if s["status"] not in ("SCHEDULED", "COMPLETED", "SCORED"):
            continue
        if s["scheduled_start"].date() == day:
            day_count += 1
    if day_count >= cyc["max_sessions_per_day"]:
        raise api_err("ERR_CYCLE_DAILY_CAPACITY_EXCEEDED",
                      "Cycle daily session capacity reached for that UTC day")
    # Temporal gate: session fits inside the closed administration window
    if (scheduled_start < cyc["administration_window_start"]
            or scheduled_end > cyc["administration_window_end"]):
        raise api_err("ERR_OUTSIDE_ADMINISTRATION_WINDOW",
                      "Session must fit inside the cycle administration window")
    # Version pin: guide_id must equal the cycle's pinned guide
    if guide_id != cyc["guide_id"]:
        raise api_err("ERR_GUIDE_VERSION_MISMATCH",
                      "guide_id must equal the cycle's pinned guide_id")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "cycle_id": cid,
        "candidate_id": candidate_id,
        "interviewer_id": interviewer_id,
        "guide_id": guide_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "completed_at": None,
        "cancellation_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["sessions"][rec["id"]] = rec
    core.recompute_interviewer_minutes(interviewer_id)
    bump(interviewer)
    return success_object(serializers.session(rec), 201)


@bp.post("/talent/sessions/<sid>/complete")
def complete_session(sid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    s = _get_session_or_404(sid)
    util.get_body()
    cyc = _own_session_cycle(ctx, s)
    if s["status"] != "SCHEDULED":
        raise api_err("ERR_INVALID_STATE", "Session must be SCHEDULED to complete")
    if cyc is not None:
        if cyc["posture"] == "FROZEN":
            raise api_err("ERR_CYCLE_FROZEN", "Cycle is FROZEN")
        if cyc["posture"] != "ACTIVE":
            raise api_err("ERR_CYCLE_NOT_ACTIVE", "Cycle must be ACTIVE")
    now = db.get_now()
    if now < s["scheduled_end"]:
        raise api_err("ERR_SESSION_NOT_ENDED",
                      "Session completes only at or after scheduled_end")
    s["status"] = "COMPLETED"
    s["completed_at"] = now
    bump(s)
    core.recompute_interviewer_minutes(s["interviewer_id"])
    return success_object(serializers.session(s))


@bp.post("/talent/sessions/<sid>/cancel")
def cancel_session(sid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    s = _get_session_or_404(sid)
    util.get_body()
    _own_session_cycle(ctx, s)
    if s["status"] != "SCHEDULED":
        raise api_err("ERR_INVALID_STATE", "Session must be SCHEDULED to cancel")
    s["status"] = "CANCELLED"
    s["cancellation_reason"] = "MANUAL"
    bump(s)
    core.recompute_interviewer_minutes(s["interviewer_id"])
    iv = db.stores["interviewers"].get(s["interviewer_id"])
    if iv is not None:
        bump(iv)
    return success_object(serializers.session(s))


@bp.post("/talent/sessions/<sid>/scorecards")
def create_scorecard(sid):
    ctx = authenticate()
    require_roles(ctx, ["Interviewer"])
    s = _get_session_or_404(sid)
    body = util.get_body()
    # Ownership: session interviewer == X-User-ID
    if s["interviewer_id"] != ctx.user_id:
        raise err_ownership("Scorecards are authored by the session's interviewer")
    # Dedicated state: session COMPLETED
    if s["status"] != "COMPLETED":
        raise api_err("ERR_SESSION_NOT_COMPLETED",
                      "Scorecard creation requires a COMPLETED session")
    cyc = _cycle_of(s)
    if cyc is not None:
        if cyc["posture"] == "FROZEN":
            raise api_err("ERR_CYCLE_FROZEN", "Cycle is FROZEN")
        if cyc["posture"] not in ("ACTIVE", "SCORING"):
            raise api_err("ERR_CYCLE_NOT_ACTIVE",
                          "Cycle posture must be ACTIVE or SCORING")
    # Ratings structure
    ratings = body.get("ratings")
    if not isinstance(ratings, list):
        raise err_invalid_request("ratings must be an array")
    if len(ratings) == 0:
        raise api_err("ERR_RATINGS_EMPTY", "ratings must contain at least one item")
    guide = db.stores["guides"].get(s["guide_id"])
    rubric = {item["competency_code"]: item for item in (guide["rubric_items"] if guide else [])}
    seen = set()
    norm_ratings = []
    for r in ratings:
        if not isinstance(r, dict):
            raise err_invalid_request("ratings entries must be objects")
        code = r.get("competency_code")
        if not isinstance(code, str) or code not in rubric or code in seen:
            raise api_err("ERR_RATING_COMPETENCY_MISMATCH",
                          "competency_code must exist in the pinned guide rubric and appear at most once")
        seen.add(code)
        rating = r.get("rating")
        if isinstance(rating, bool) or not isinstance(rating, int):
            raise err_invalid_request("rating must be an integer")
        if rating < 1 or rating > rubric[code]["scale_max"]:
            raise api_err("ERR_RATING_OUT_OF_RANGE",
                          "rating must be within 1..scale_max of its rubric item")
        norm_ratings.append({"competency_code": code, "rating": rating})
    # One non-VOIDED scorecard per session (tier 10, before tier-16 enum check)
    for sc in db.stores["scorecards"].values():
        if sc["session_id"] == sid and sc["status"] != "VOIDED":
            raise api_err("ERR_DUPLICATE_SCORECARD",
                          "Session already has a non-VOIDED scorecard")
    recommendation = req_enum(body, "overall_recommendation", RECOMMENDATIONS)
    now = db.get_now()
    rec = {
        "id": new_id(),
        "session_id": sid,
        "interviewer_id": s["interviewer_id"],
        "candidate_id": s["candidate_id"],
        "ratings": norm_ratings,
        "overall_recommendation": recommendation,
        "status": "DRAFT",
        "weighted_total": None,
        "submitted_at": None,
        "voided_at": None,
        "void_reason": None,
        "redacted": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["scorecards"][rec["id"]] = rec
    return success_object(serializers.scorecard(rec), 201)
