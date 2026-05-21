"""Interview + InterviewFeedback routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format, now, parse_iso
from ..common import bump, get_json_body, positive_int, require_enum, require_fields, require_str, stamp_new
from ..errors import ApiError
from ..lookups import path_application, path_interview, ref_interviewer
from ..response import respond
from ..serializers import serialize_interview, serialize_interview_feedback
from ..services import recompute_panel_average
from ..store import store


interviews_bp = Blueprint("interviews", __name__)


INTERVIEW_BUFFER_MIN = 15
RECOMMENDATIONS = {"STRONG_HIRE", "HIRE", "NO_HIRE", "STRONG_NO_HIRE"}


def _intervals_overlap_with_buffer(
    new_start, new_end, ex_start, ex_end, buffer_min: int
) -> bool:
    buf = timedelta(minutes=buffer_min)
    ex_start_b = ex_start - buf
    ex_end_b = ex_end + buf
    # Treat each interval as closed; the buffer makes adjacency a conflict.
    return not (new_end < ex_start_b or new_start > ex_end_b)


@interviews_bp.post("/applications/<aid>/interviews")
@require_auth("Recruiter")
def schedule_interview(aid):
    body = get_json_body()
    require_fields(body, "interviewer_id", "scheduled_start_at", "scheduled_end_at")
    interviewer_id = require_str(body["interviewer_id"], "interviewer_id")
    start_raw = require_str(body["scheduled_start_at"], "scheduled_start_at")
    end_raw = require_str(body["scheduled_end_at"], "scheduled_end_at")
    try:
        start_dt = parse_iso(start_raw)
        end_dt = parse_iso(end_raw)
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    if end_dt <= start_dt:
        raise ApiError("ERR_VALIDATION", "scheduled_end_at must be strictly after scheduled_start_at")

    with store.lock:
        app = path_application(aid)
        req = store.requisitions.get(app["requisition_id"])
        if req is None:
            raise ApiError("ERR_NOT_FOUND", "Parent Requisition not found")
        if g.user_id != req["recruiter_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the owning recruiter may schedule interviews")
        ref_interviewer(interviewer_id)

        # Double-booking check.
        for existing in store.interviews.values():
            if existing["interviewer_id"] != interviewer_id or existing["status"] != "SCHEDULED":
                continue
            ex_s = parse_iso(existing["scheduled_start_at"])
            ex_e = parse_iso(existing["scheduled_end_at"])
            if _intervals_overlap_with_buffer(start_dt, end_dt, ex_s, ex_e, INTERVIEW_BUFFER_MIN):
                raise ApiError(
                    "ERR_INTERVIEWER_DOUBLE_BOOKED",
                    "Interviewer has an overlapping scheduled interview (with 15-min buffer)",
                )

        interview = stamp_new({
            "application_id": aid,
            "interviewer_id": interviewer_id,
            "scheduled_start_at": iso_format(start_dt),
            "scheduled_end_at": iso_format(end_dt),
            "status": "SCHEDULED",
        })
        store.interviews[interview["id"]] = interview
    return respond(serialize_interview(interview), 201)


@interviews_bp.get("/interviews/<iid>")
@require_auth("Recruiter", "HiringManager", "Interviewer", "PlatformAdmin")
def get_interview(iid):
    with store.lock:
        return respond(serialize_interview(path_interview(iid)))


@interviews_bp.post("/interviews/<iid>/complete")
@require_auth("Recruiter", "Interviewer")
def complete_interview(iid):
    with store.lock:
        interview = path_interview(iid)
        if interview["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Interview is not SCHEDULED")
        # RBAC ownership.
        if g.user_role == "Interviewer" and g.user_id != interview["interviewer_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the assigned interviewer may complete this interview")
        if g.user_role == "Recruiter":
            app = store.applications.get(interview["application_id"])
            req = store.requisitions.get(app["requisition_id"]) if app else None
            if req is None or g.user_id != req["recruiter_id"]:
                raise ApiError("ERR_FORBIDDEN", "Only the owning recruiter may complete this interview")

        # Timing check.
        if now() < parse_iso(interview["scheduled_end_at"]):
            raise ApiError(
                "ERR_INTERVIEW_TIMING",
                "Interview cannot be completed before scheduled_end_at",
            )
        interview["status"] = "COMPLETED"
        bump(interview)
        recompute_panel_average(interview["application_id"])
        return respond(serialize_interview(interview))


@interviews_bp.post("/interviews/<iid>/no-show")
@require_auth("Recruiter", "Interviewer")
def no_show_interview(iid):
    with store.lock:
        interview = path_interview(iid)
        if interview["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Interview is not SCHEDULED")
        if g.user_role == "Interviewer" and g.user_id != interview["interviewer_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the assigned interviewer may mark no-show")
        if g.user_role == "Recruiter":
            app = store.applications.get(interview["application_id"])
            req = store.requisitions.get(app["requisition_id"]) if app else None
            if req is None or g.user_id != req["recruiter_id"]:
                raise ApiError("ERR_FORBIDDEN", "Only the owning recruiter may mark no-show")
        if now() < parse_iso(interview["scheduled_end_at"]):
            raise ApiError(
                "ERR_INTERVIEW_TIMING",
                "Interview cannot be marked NO_SHOW before scheduled_end_at",
            )
        interview["status"] = "NO_SHOW"
        bump(interview)
        return respond(serialize_interview(interview))


@interviews_bp.post("/interviews/<iid>/cancel")
@require_auth("Recruiter")
def cancel_interview(iid):
    with store.lock:
        interview = path_interview(iid)
        if interview["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Interview is not SCHEDULED")
        app = store.applications.get(interview["application_id"])
        req = store.requisitions.get(app["requisition_id"]) if app else None
        if req is None or g.user_id != req["recruiter_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the owning recruiter may cancel an interview")
        if now() >= parse_iso(interview["scheduled_start_at"]):
            raise ApiError(
                "ERR_INTERVIEW_TIMING",
                "Interview cannot be cancelled at or after scheduled_start_at",
            )
        interview["status"] = "CANCELLED"
        bump(interview)
        return respond(serialize_interview(interview))


@interviews_bp.post("/interviews/<iid>/feedback")
@require_auth("Interviewer")
def submit_feedback(iid):
    body = get_json_body()
    require_fields(body, "overall_score", "recommendation")
    score = body["overall_score"]
    if isinstance(score, bool) or not isinstance(score, int):
        raise ApiError("ERR_VALIDATION", "overall_score must be an integer")
    if score < 1 or score > 5:
        raise ApiError("ERR_VALIDATION", "overall_score must be between 1 and 5 inclusive")
    recommendation = require_enum(body["recommendation"], "recommendation", RECOMMENDATIONS)

    with store.lock:
        interview = path_interview(iid)
        if g.user_id != interview["interviewer_id"]:
            raise ApiError(
                "ERR_FORBIDDEN",
                "Only the assigned interviewer may submit feedback for this interview",
            )
        # Segregation of duties: EEO certification gate.
        app = store.applications.get(interview["application_id"])
        candidate = store.candidates.get(app["candidate_id"]) if app else None
        interviewer = store.interviewers.get(interview["interviewer_id"])
        if candidate and candidate.get("is_in_eeo_protected_class"):
            if not (interviewer and interviewer.get("is_certified_for_eeo")):
                raise ApiError(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "Interviewer must be is_certified_for_eeo to score a protected-class candidate",
                )
        ts = iso_format(now())
        feedback = stamp_new(
            {
                "interview_id": iid,
                "interviewer_id": interview["interviewer_id"],
                "overall_score": score,
                "recommendation": recommendation,
                "submitted_at": ts,
            },
            with_common=False,
        )
        store.interview_feedback[feedback["id"]] = feedback
        recompute_panel_average(interview["application_id"])
    return respond(serialize_interview_feedback(feedback), 201)


@interviews_bp.get("/interviews/<iid>/feedback")
@require_auth("Recruiter", "HiringManager", "Interviewer")
def list_feedback(iid):
    with store.lock:
        path_interview(iid)
        feedbacks = sorted(
            (f for f in store.interview_feedback.values() if f["interview_id"] == iid),
            key=lambda f: f["created_at"],
        )
        return respond([serialize_interview_feedback(f) for f in feedbacks])
