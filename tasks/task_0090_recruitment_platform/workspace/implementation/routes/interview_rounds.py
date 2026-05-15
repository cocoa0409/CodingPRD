"""InterviewRound routes — create, publish slots, candidate-confirm, feedback, read."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Tuple

from flask import Blueprint, jsonify

from auth import get_caller, require_hr_bound_to_company, require_roles
from clock import clock, format_iso, parse_iso
from errors import (
    ERR_FEEDBACK_INVALID,
    ERR_FORBIDDEN,
    ERR_INTERVIEWER_BUSY,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SLOT_IN_PAST,
    ERR_VALIDATION,
    raise_err,
)
from request_body import check_version, get_json_body, require_field
from response import success_object
from routes.candidates import check_resume_visible_to_hr
from services.cascade import cancel_rounds_for_application
from store import append_audit, bump, init_common_fields, lock, store


bp = Blueprint("interview_rounds", __name__)

_MODE_VALUES = {"ONSITE", "PHONE", "VIDEO"}
_FEEDBACK_VALUES = {"PASS", "FAIL", "HOLD"}


def _serialize(r: Dict[str, Any]) -> Dict[str, Any]:
    return dict(r)


def _interviewer_collides(interviewer_id: str, start, end, exclude_round_id: str = None) -> bool:
    """Return True if any existing SCHEDULED round for interviewer overlaps [start, end)."""
    for r in store.interview_rounds.values():
        if r.get("round_status") != "SCHEDULED":
            continue
        if exclude_round_id is not None and r["id"] == exclude_round_id:
            continue
        if interviewer_id not in (r.get("interviewer_user_ids") or []):
            continue
        try:
            rs = parse_iso(r["scheduled_start_at"])
            re = parse_iso(r["scheduled_end_at"])
        except Exception:
            continue
        if start < re and rs < end:
            return True
    return False


@bp.post("/recruitment/applications/<aid>/interview-rounds")
def create_interview_round(aid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    application = store.applications.get(aid)
    if application is None:
        raise_err(ERR_NOT_FOUND, "Application not found.")
    require_hr_bound_to_company(caller, application["company_id"])
    candidate = store.candidates.get(application.get("candidate_id"))
    if candidate is not None:
        check_resume_visible_to_hr(candidate, application["company_id"])

    body = get_json_body()
    mode = require_field(body, "mode")
    interviewer_ids = require_field(body, "interviewer_user_ids")
    if mode not in _MODE_VALUES:
        raise_err(ERR_VALIDATION, "mode invalid.")
    if not isinstance(interviewer_ids, list) or not interviewer_ids:
        raise_err(ERR_VALIDATION, "interviewer_user_ids must be non-empty array.")
    for iid in interviewer_ids:
        if not isinstance(iid, str) or iid not in store.hr_users:
            raise_err(ERR_VALIDATION, "interviewer_user_ids contains unknown HrUser id.")

    # State: first round requires FORWARDED→INTERVIEW; subsequent rounds require INTERVIEW.
    existing_rounds = [r for r in store.interview_rounds.values() if r.get("application_id") == aid]
    current_status = application.get("application_status")
    if not existing_rounds:
        if current_status != "FORWARDED":
            raise_err(ERR_INVALID_STATE, "Application must be FORWARDED to start interviews.")
    else:
        if current_status != "INTERVIEW":
            raise_err(ERR_INVALID_STATE, "Application not in INTERVIEW state.")

    round_index = len(existing_rounds) + 1
    row = init_common_fields(
        {
            "application_id": aid,
            "round_index": round_index,
            "mode": mode,
            "interviewer_user_ids": list(interviewer_ids),
            "candidate_time_slot_options": [],
            "scheduled_start_at": None,
            "scheduled_end_at": None,
            "round_status": "DRAFT",
            "feedback_decision": None,
        }
    )
    store.interview_rounds[row["id"]] = row
    append_audit(
        subject_entity="InterviewRound",
        subject_id=row["id"],
        event_kind="STATE_TRANSITION",
        from_state=None,
        to_state="DRAFT",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    # First round advances application FORWARDED→INTERVIEW
    if not existing_rounds:
        application["application_status"] = "INTERVIEW"
        bump(application)
        append_audit(
            subject_entity="Application",
            subject_id=application["id"],
            event_kind="STATE_TRANSITION",
            from_state="FORWARDED",
            to_state="INTERVIEW",
            actor_role=caller.role,
            actor_user_id=caller.user_id,
        )
    body_out, status = success_object(_serialize(row), 201)
    return jsonify(body_out), status


@bp.post("/recruitment/interview-rounds/<rid>/publish-slots")
def publish_slots(rid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    r = store.interview_rounds.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, "InterviewRound not found.")
    application = store.applications.get(r["application_id"])
    if application is None:
        raise_err(ERR_NOT_FOUND, "Parent application missing.")
    require_hr_bound_to_company(caller, application["company_id"])
    body = get_json_body()
    check_version(body, r)
    slot_options = require_field(body, "candidate_time_slot_options")
    if not isinstance(slot_options, list) or not slot_options:
        raise_err(ERR_VALIDATION, "candidate_time_slot_options must be non-empty array.")

    if r.get("round_status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Round not in DRAFT.")
    if not r.get("interviewer_user_ids") or not r.get("mode"):
        raise_err(ERR_VALIDATION, "interviewer_user_ids and mode must be set on the round.")

    parsed_starts: List = []
    now = clock.now()
    for s in slot_options:
        if not isinstance(s, str) or not s:
            raise_err(ERR_VALIDATION, "Slot must be an ISO8601 string.")
        try:
            ts = parse_iso(s)
        except Exception:
            raise_err(ERR_VALIDATION, "Invalid ISO8601 slot.")
        if ts <= now:
            raise_err(ERR_SLOT_IN_PAST, "Slot in the past.")
        parsed_starts.append(ts)

    # Interviewer availability: any proposed slot colliding with an existing SCHEDULED round
    # for any of the interviewers is a reject (ERR_INTERVIEWER_BUSY).
    for start in parsed_starts:
        end = start + timedelta(minutes=60)
        for iid in r["interviewer_user_ids"]:
            if _interviewer_collides(iid, start, end, exclude_round_id=r["id"]):
                raise_err(ERR_INTERVIEWER_BUSY, "Interviewer busy in proposed slot.")

    r["candidate_time_slot_options"] = list(slot_options)
    r["round_status"] = "AWAITING_CANDIDATE"
    bump(r)
    append_audit(
        subject_entity="InterviewRound",
        subject_id=r["id"],
        event_kind="STATE_TRANSITION",
        from_state="DRAFT",
        to_state="AWAITING_CANDIDATE",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(r))
    return jsonify(body_out), status


@bp.post("/recruitment/interview-rounds/<rid>/candidate-confirm")
def candidate_confirm(rid: str):
    caller = get_caller()
    require_roles(caller, ["Candidate"])
    r = store.interview_rounds.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, "InterviewRound not found.")
    application = store.applications.get(r["application_id"])
    if application is None:
        raise_err(ERR_NOT_FOUND, "Parent application missing.")
    if application.get("candidate_id") != caller.user_id:
        raise_err(ERR_FORBIDDEN, "Cannot confirm another candidate's round.")
    body = get_json_body()
    check_version(body, r)
    selected_slot = require_field(body, "selected_slot")
    if not isinstance(selected_slot, str) or not selected_slot:
        raise_err(ERR_VALIDATION, "selected_slot required.")
    if r.get("round_status") != "AWAITING_CANDIDATE":
        raise_err(ERR_INVALID_STATE, "Round not awaiting candidate.")
    if selected_slot not in (r.get("candidate_time_slot_options") or []):
        raise_err(ERR_VALIDATION, "selected_slot not in published options.")
    try:
        start = parse_iso(selected_slot)
    except Exception:
        raise_err(ERR_VALIDATION, "Invalid ISO8601 selected_slot.")
    end = start + timedelta(minutes=60)
    for iid in r["interviewer_user_ids"]:
        if _interviewer_collides(iid, start, end, exclude_round_id=r["id"]):
            raise_err(ERR_INTERVIEWER_BUSY, "Interviewer busy at selected slot.")

    r["scheduled_start_at"] = format_iso(start)
    r["scheduled_end_at"] = format_iso(end)
    r["round_status"] = "SCHEDULED"
    bump(r)
    append_audit(
        subject_entity="InterviewRound",
        subject_id=r["id"],
        event_kind="STATE_TRANSITION",
        from_state="AWAITING_CANDIDATE",
        to_state="SCHEDULED",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(r))
    return jsonify(body_out), status


@bp.post("/recruitment/interview-rounds/<rid>/submit-feedback")
def submit_feedback(rid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    r = store.interview_rounds.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, "InterviewRound not found.")
    application = store.applications.get(r["application_id"])
    if application is None:
        raise_err(ERR_NOT_FOUND, "Parent application missing.")
    require_hr_bound_to_company(caller, application["company_id"])
    body = get_json_body()
    check_version(body, r)
    if r.get("round_status") != "FEEDBACK_PENDING":
        raise_err(ERR_INVALID_STATE, "Round not awaiting feedback.")
    decision = require_field(body, "feedback_decision")
    if decision not in _FEEDBACK_VALUES:
        raise_err(ERR_FEEDBACK_INVALID, "feedback_decision invalid.")

    r["feedback_decision"] = decision
    if decision == "PASS":
        r["round_status"] = "PASSED"
        bump(r)
        append_audit(
            subject_entity="InterviewRound",
            subject_id=r["id"],
            event_kind="STATE_TRANSITION",
            from_state="FEEDBACK_PENDING",
            to_state="PASSED",
            actor_role=caller.role,
            actor_user_id=caller.user_id,
        )
    elif decision == "FAIL":
        r["round_status"] = "FAILED"
        bump(r)
        append_audit(
            subject_entity="InterviewRound",
            subject_id=r["id"],
            event_kind="STATE_TRANSITION",
            from_state="FEEDBACK_PENDING",
            to_state="FAILED",
            actor_role=caller.role,
            actor_user_id=caller.user_id,
        )
        # Cascade: parent Application → REJECTED
        prev_app_state = application["application_status"]
        if prev_app_state not in {"REJECTED", "CLOSED"}:
            application["application_status"] = "REJECTED"
            bump(application)
            append_audit(
                subject_entity="Application",
                subject_id=application["id"],
                event_kind="STATE_TRANSITION",
                from_state=prev_app_state,
                to_state="REJECTED",
                actor_role=caller.role,
                actor_user_id=caller.user_id,
            )
            cancel_rounds_for_application(application["id"], actor_role=caller.role, actor_user_id=caller.user_id)
    else:
        # HOLD — round stays in FEEDBACK_PENDING per spec
        bump(r)
    body_out, status = success_object(_serialize(r))
    return jsonify(body_out), status


@bp.get("/recruitment/interview-rounds/<rid>")
def get_interview_round(rid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser", "Candidate"])
    r = store.interview_rounds.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, "InterviewRound not found.")
    application = store.applications.get(r["application_id"])
    if caller.role == "Candidate":
        if application is None or application.get("candidate_id") != caller.user_id:
            raise_err(ERR_FORBIDDEN, "Cannot view another candidate's round.")
    else:
        require_hr_bound_to_company(caller, application["company_id"])
    body_out, status = success_object(_serialize(r))
    return jsonify(body_out), status
