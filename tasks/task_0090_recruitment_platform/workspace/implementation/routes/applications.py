"""Application routes."""
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify

from auth import get_caller, require_hr_bound_to_company, require_roles
from clock import clock, iso_now, parse_iso
from errors import (
    ERR_CANDIDATE_RATE_LIMIT,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from request_body import check_version, get_json_body, require_field
from response import success_object
from routes.candidates import check_resume_visible_to_hr
from services.cascade import cancel_rounds_for_application
from store import append_audit, bump, init_common_fields, lock, store


bp = Blueprint("applications", __name__)


_SOURCE_CHANNELS = {"DIRECT", "ONE_CLICK", "HEADHUNTER"}


def _serialize(a: Dict[str, Any]) -> Dict[str, Any]:
    return dict(a)


def _count_recent_applications(candidate_id: str) -> int:
    now = clock.now()
    count = 0
    for a in store.applications.values():
        if a.get("candidate_id") != candidate_id:
            continue
        try:
            ts = parse_iso(a.get("created_at", ""))
        except Exception:
            continue
        delta = (now - ts).total_seconds()
        if 0 <= delta < 60:
            count += 1
    return count


@bp.post("/recruitment/applications")
def create_application():
    caller = get_caller()
    require_roles(caller, ["Candidate"])
    body = get_json_body()
    candidate_id = require_field(body, "candidate_id")
    job_posting_id = require_field(body, "job_posting_id")
    source_channel = body.get("source_channel", "DIRECT")
    headhunter_contract_id = body.get("headhunter_contract_id")

    if source_channel not in _SOURCE_CHANNELS:
        raise_err(ERR_VALIDATION, "source_channel invalid.")

    candidate = store.candidates.get(candidate_id)
    if candidate is None:
        raise_err(ERR_REFERENCE_NOT_FOUND, "candidate_id not found.")
    posting = store.job_postings.get(job_posting_id)
    if posting is None:
        raise_err(ERR_REFERENCE_NOT_FOUND, "job_posting_id not found.")
    if source_channel == "HEADHUNTER":
        if not headhunter_contract_id:
            raise_err(ERR_VALIDATION, "headhunter_contract_id required for HEADHUNTER channel.")
        contract = store.headhunter_contracts.get(headhunter_contract_id)
        if contract is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "headhunter_contract_id not found.")

    # Candidate must be the acting caller
    if caller.user_id != candidate_id:
        raise_err(ERR_FORBIDDEN, "Cannot apply on behalf of another candidate.")

    # Anti-spam rate limit (priority 15) — at most 5 in last 60s window; sixth blocked.
    in_window = _count_recent_applications(candidate_id)
    if in_window >= 5:
        raise_err(ERR_CANDIDATE_RATE_LIMIT, "Application rate limit exceeded.")

    row = init_common_fields(
        {
            "candidate_id": candidate_id,
            "job_posting_id": job_posting_id,
            "company_id": posting.get("company_id"),
            "application_status": "SUBMITTED",
            "read_at": None,
            "forwarded_at": None,
            "source_channel": source_channel,
            "headhunter_contract_id": headhunter_contract_id if source_channel == "HEADHUNTER" else None,
        }
    )
    store.applications[row["id"]] = row
    # Update candidate's last_application_at
    candidate["last_application_at"] = row["created_at"]
    bump(candidate)
    append_audit(
        subject_entity="Application",
        subject_id=row["id"],
        event_kind="STATE_TRANSITION",
        from_state=None,
        to_state="SUBMITTED",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(row), 201)
    return jsonify(body_out), status


@bp.get("/recruitment/applications/<aid>")
def get_application(aid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser", "Candidate"])
    a = store.applications.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, "Application not found.")
    if caller.role == "Candidate":
        if a.get("candidate_id") != caller.user_id:
            raise_err(ERR_FORBIDDEN, "Cannot view another candidate's application.")
    else:
        # HR-side caller must be bound to the application's company
        require_hr_bound_to_company(caller, a["company_id"])
    body_out, status = success_object(_serialize(a))
    return jsonify(body_out), status


@bp.post("/recruitment/applications/<aid>/mark-read")
def mark_read(aid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    a = store.applications.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, "Application not found.")
    require_hr_bound_to_company(caller, a["company_id"])
    body = get_json_body()
    check_version(body, a)
    if a.get("application_status") != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Application not SUBMITTED.")
    posting = store.job_postings.get(a.get("job_posting_id"))
    if posting is None or posting.get("posting_status") != "LIVE":
        raise_err(ERR_INVALID_STATE, "JobPosting not LIVE.")
    a["application_status"] = "READ"
    a["read_at"] = iso_now()
    bump(a)
    append_audit(
        subject_entity="Application",
        subject_id=a["id"],
        event_kind="STATE_TRANSITION",
        from_state="SUBMITTED",
        to_state="READ",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(a))
    return jsonify(body_out), status


@bp.post("/recruitment/applications/<aid>/forward")
def forward(aid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    a = store.applications.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, "Application not found.")
    require_hr_bound_to_company(caller, a["company_id"])
    candidate = store.candidates.get(a.get("candidate_id"))
    if candidate is not None:
        check_resume_visible_to_hr(candidate, a["company_id"])
    body = get_json_body()
    check_version(body, a)
    if a.get("application_status") != "READ":
        raise_err(ERR_INVALID_STATE, "Application not READ.")
    a["application_status"] = "FORWARDED"
    a["forwarded_at"] = iso_now()
    bump(a)
    append_audit(
        subject_entity="Application",
        subject_id=a["id"],
        event_kind="STATE_TRANSITION",
        from_state="READ",
        to_state="FORWARDED",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(a))
    return jsonify(body_out), status


@bp.post("/recruitment/applications/<aid>/reject")
def reject_application(aid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    a = store.applications.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, "Application not found.")
    require_hr_bound_to_company(caller, a["company_id"])
    body = get_json_body()
    check_version(body, a)
    if a.get("application_status") in {"REJECTED", "CLOSED"}:
        raise_err(ERR_INVALID_STATE, "Application already terminal.")
    from_state = a["application_status"]
    a["application_status"] = "REJECTED"
    bump(a)
    cancel_rounds_for_application(a["id"], actor_role=caller.role, actor_user_id=caller.user_id)
    append_audit(
        subject_entity="Application",
        subject_id=a["id"],
        event_kind="STATE_TRANSITION",
        from_state=from_state,
        to_state="REJECTED",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(a))
    return jsonify(body_out), status
