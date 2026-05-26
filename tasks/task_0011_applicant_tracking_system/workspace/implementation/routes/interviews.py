"""Interview + InterviewFeedback endpoints."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import clock
import db
from auth import require_role
from common import (
    get_json_or_400,
    require_str,
    require_int,
    new_id,
    now_iso,
    parse_pagination,
    paginate,
    get_or_404,
    fk_or_404,
    stamp_update,
    round_half_up_dp,
)
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PANELIST_CONFLICT,
    ERR_INVALID_PANEL,
    ERR_PANELIST_NOT_ASSIGNED,
    ERR_FEEDBACK_INCOMPLETE,
    ERR_INTERVIEW_OVERLAP_APPLICATION,
    ERR_INTERVIEW_OVERLAP_PANELIST,
)
from response import success_object, success_array
from serializers import ser_interview, ser_interview_feedback


bp = Blueprint("interviews", __name__)


def _parse_iso_or_400(val):
    if not isinstance(val, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "scheduled_at must be ISO 8601 string")
    try:
        return clock.parse_iso(val)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "scheduled_at invalid ISO 8601")


@bp.post("/ats/interviews")
def create_interview():
    require_role({"Recruiter"})
    body = get_json_or_400()
    application_id = require_str(body, "application_id")
    round_number = require_int(body, "round_number", minimum=1)
    scheduled_at_raw = body.get("scheduled_at")
    scheduled_dt = _parse_iso_or_400(scheduled_at_raw)
    duration_minutes = require_int(body, "duration_minutes", minimum=15)
    panel = body.get("panel_user_ids")
    if not isinstance(panel, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "panel_user_ids must be array")
    for x in panel:
        if not isinstance(x, str) or not x:
            raise ApiError(ERR_INVALID_REQUEST, 400, "panel_user_ids must contain non-empty strings")

    # FK
    app = fk_or_404(db.applications, application_id, "application")
    candidate = db.candidates[app["candidate_id"]]

    # Panelist conflict (priority 8) — must fire before INVALID_PANEL per PRD §2.10 ordering.
    if candidate.get("referrer_user_id") and candidate["referrer_user_id"] in panel:
        raise ApiError(ERR_PANELIST_CONFLICT, 422, "panel contains candidate's referrer")

    # Panel shape (priority 12).
    if len(panel) < 1 or len(panel) > 5 or len(set(panel)) != len(panel):
        raise ApiError(ERR_INVALID_PANEL, 422, "panel size 1..5 with no duplicates")

    # Per-application overlap (priority 14.5).
    new_start = scheduled_dt
    new_end = scheduled_dt + timedelta(minutes=duration_minutes)
    for other in db.interviews.values():
        if other["application_id"] != application_id:
            continue
        if other["status"] != "SCHEDULED":
            continue
        o_start = clock.parse_iso(other["scheduled_at"])
        o_end = o_start + timedelta(minutes=other["duration_minutes"])
        # Half-open [start, end): overlap iff new_start < o_end and o_start < new_end.
        if new_start < o_end and o_start < new_end:
            raise ApiError(ERR_INTERVIEW_OVERLAP_APPLICATION, 422, "overlapping interview on application")

    # Per-panelist buffered overlap (priority 14.6).
    buffered_start = new_start - timedelta(minutes=15)
    buffered_end = new_end + timedelta(minutes=15)
    panel_set = set(panel)
    for other in db.interviews.values():
        if other["status"] != "SCHEDULED":
            continue
        other_panel = set(other["panel_user_ids"])
        if not (panel_set & other_panel):
            continue
        o_start = clock.parse_iso(other["scheduled_at"]) - timedelta(minutes=15)
        o_end = clock.parse_iso(other["scheduled_at"]) + timedelta(minutes=other["duration_minutes"]) + timedelta(minutes=15)
        # Buffered half-open intervals.
        if buffered_start < o_end and o_start < buffered_end:
            raise ApiError(ERR_INTERVIEW_OVERLAP_PANELIST, 422, "panelist double-booked")

    # Compute whether this is the first interview on the application (for the SCREENING->INTERVIEWING cascade).
    is_first = not any(
        i for i in db.interviews.values()
        if i["application_id"] == application_id
    )

    iv = {
        "id": new_id(),
        "application_id": application_id,
        "round_number": round_number,
        "scheduled_at": clock.iso(scheduled_dt),
        "duration_minutes": duration_minutes,
        "panel_user_ids": list(panel),
        "status": "SCHEDULED",
        "aggregate_score": None,
        "recommendation": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.interviews[iv["id"]] = iv

    # Cascade application SCREENING -> INTERVIEWING if first interview.
    if is_first and app["status"] == "SCREENING":
        app["status"] = "INTERVIEWING"
        stamp_update(app)

    return success_object(ser_interview(iv), status=201)


@bp.get("/ats/interviews/<iv_id>")
def read_interview(iv_id):
    require_role({"Recruiter", "HiringManager", "PlatformAdmin"})
    iv = get_or_404(db.interviews, iv_id, "interview")
    return success_object(ser_interview(iv), status=200)


@bp.get("/ats/interviews")
def list_interviews():
    require_role({"Recruiter", "HiringManager", "PlatformAdmin"})
    limit, offset = parse_pagination()
    rows = list(db.interviews.values())
    app_filter = request.args.get("application_id")
    if app_filter:
        rows = [i for i in rows if i["application_id"] == app_filter]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([ser_interview(i) for i in page], limit, offset, total, status=200)


@bp.post("/ats/interviews/<iv_id>/complete")
def complete_interview(iv_id):
    require_role({"Recruiter"})
    iv = get_or_404(db.interviews, iv_id, "interview")
    if iv["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "interview not in SCHEDULED")
    # All panelists must have submitted feedback.
    submitted = {
        f["panelist_user_id"] for f in db.interview_feedback.values()
        if f["interview_id"] == iv_id
    }
    missing = [p for p in iv["panel_user_ids"] if p not in submitted]
    if missing:
        raise ApiError(ERR_FEEDBACK_INCOMPLETE, 409, "missing feedback from panelists")
    scores = [f["score"] for f in db.interview_feedback.values() if f["interview_id"] == iv_id]
    mean = sum(scores) / len(scores)
    aggregate = round_half_up_dp(mean, 2)
    if aggregate >= 4.50:
        rec = "STRONG_HIRE"
    elif aggregate >= 3.50:
        rec = "HIRE"
    elif aggregate >= 2.50:
        rec = "NO_HIRE"
    else:
        rec = "STRONG_NO_HIRE"
    iv["status"] = "COMPLETED"
    iv["aggregate_score"] = aggregate
    iv["recommendation"] = rec
    stamp_update(iv)
    return success_object(ser_interview(iv), status=200)


@bp.post("/ats/interviews/<iv_id>/cancel")
def cancel_interview(iv_id):
    require_role({"Recruiter"})
    iv = get_or_404(db.interviews, iv_id, "interview")
    if iv["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "interview not in SCHEDULED")
    iv["status"] = "CANCELLED"
    stamp_update(iv)
    return success_object(ser_interview(iv), status=200)


# ---------------------------------------------------------------------------
# InterviewFeedback
# ---------------------------------------------------------------------------


@bp.post("/ats/interview-feedback")
def create_feedback():
    require_role({"HiringManager", "Recruiter"})
    body = get_json_or_400()
    interview_id = require_str(body, "interview_id")
    panelist_user_id = require_str(body, "panelist_user_id")
    score = require_int(body, "score", minimum=1, maximum=5)
    comments = body.get("comments", "")
    if not isinstance(comments, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "comments must be string")

    iv = fk_or_404(db.interviews, interview_id, "interview")
    if panelist_user_id not in iv["panel_user_ids"]:
        raise ApiError(ERR_PANELIST_NOT_ASSIGNED, 422, "panelist not in interview panel")

    fb = {
        "id": new_id(),
        "interview_id": interview_id,
        "panelist_user_id": panelist_user_id,
        "score": score,
        "comments": comments,
        "created_at": now_iso(),
    }
    db.interview_feedback[fb["id"]] = fb
    return success_object(ser_interview_feedback(fb), status=201)


@bp.get("/ats/interview-feedback")
def list_feedback():
    require_role({"Recruiter", "HiringManager", "PlatformAdmin"})
    limit, offset = parse_pagination()
    rows = list(db.interview_feedback.values())
    iv_filter = request.args.get("interview_id")
    if iv_filter:
        rows = [f for f in rows if f["interview_id"] == iv_filter]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([ser_interview_feedback(f) for f in page], limit, offset, total, status=200)
