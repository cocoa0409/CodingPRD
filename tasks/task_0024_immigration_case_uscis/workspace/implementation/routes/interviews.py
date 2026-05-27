"""Interview endpoints: schedule, list, get, complete, no-show."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_CASE_TYPE_NOT_APPLICABLE,
    ERR_VISA_RETROGRESSED,
    ERR_APPT_TOO_SOON,
    ERR_APPT_OVERLAP_SAME_CASE,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields,
    require_enum,
    require_string,
    lookup_or_404,
    ensure_case_ownership,
    parse_appt_dt,
    parse_clock_dt,
    evaluation_month_from_clock,
)
from services.events import append_event
from services.calculations import (
    evaluate_visa_availability,
    TERMINAL_CASE_STATES,
)


bp = Blueprint("interviews", __name__)


ALL_ROLES = ["Applicant", "Attorney", "Officer", "FieldOfficeAdmin"]
APPT_DURATION_MIN = 60
SEVEN_DAYS = timedelta(days=7)
GRACE_24H = timedelta(hours=24)
DECISIONS = {"APPROVE", "DENY", "NEEDS_REVIEW"}


def _check_overlap_same_case(case_id: str, new_dt) -> None:
    new_start = new_dt
    new_end = new_dt + timedelta(minutes=APPT_DURATION_MIN)
    for a in db.interviews.values():
        if a.get("case_id") != case_id:
            continue
        if a.get("status") != "SCHEDULED":
            continue
        existing = db.parse_iso_dt(a.get("scheduled_at"))
        if existing is None:
            continue
        existing_end = existing + timedelta(minutes=APPT_DURATION_MIN)
        if new_start < existing_end and existing < new_end:
            raise APIError(ERR_APPT_OVERLAP_SAME_CASE, 409, "Interview overlaps existing one for this case")


# ---------- POST /uscis/cases/{id}/interviews -------------------------------

@bp.post("/uscis/cases/<rid>/interviews")
def schedule_interview(rid: str):
    require_auth(["Officer"])()
    case = lookup_or_404(db.cases, rid, "Case")

    if case.get("status") in TERMINAL_CASE_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Case is already terminal")
    if case.get("status") != "UNDER_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, f"Case must be UNDER_REVIEW (was {case.get('status')})")
    if case.get("case_type") != "I-485":
        raise APIError(ERR_CASE_TYPE_NOT_APPLICABLE, 422, "Interviews only apply to I-485")

    # No open RFE on this case.
    for r in db.rfes.values():
        if r.get("case_id") == case["id"] and r.get("status") == "ISSUED":
            raise APIError(ERR_INVALID_STATE, 409, "Cannot schedule interview while RFE is open")

    # Visa availability gate (I-485 only).
    applicant = db.applicants.get(case.get("applicant_id"))
    if applicant is not None and case.get("preference_category"):
        avail = evaluate_visa_availability(
            priority_date_iso=case["priority_date"],
            preference_category=case["preference_category"],
            country=applicant["country_of_chargeability"],
            chart_type="FINAL_ACTION",
            evaluation_month=evaluation_month_from_clock(),
            visa_bulletin_store=db.visa_bulletin,
        )
        if avail != "CURRENT":
            raise APIError(ERR_VISA_RETROGRESSED, 422, "Visa unavailable at evaluation month for I-485")

    body = get_json_body()
    require_fields(body, ["scheduled_at", "field_office_code"])
    scheduled_at = body["scheduled_at"]
    field_office = body["field_office_code"]
    require_string(field_office, "field_office_code")
    new_dt = parse_appt_dt(scheduled_at, "scheduled_at")
    now_dt = parse_clock_dt()

    if new_dt < now_dt + SEVEN_DAYS:
        raise APIError(ERR_APPT_TOO_SOON, 422, "Interview must be at least 7 days in the future")
    _check_overlap_same_case(case["id"], new_dt)

    appt = {
        "case_id": case["id"],
        "scheduled_at": scheduled_at,
        "field_office_code": field_office,
        "status": "SCHEDULED",
        "decision_after_interview": None,
    }
    db.stamp_common(appt)
    db.interviews[appt["id"]] = appt

    prior = case["status"]
    case["status"] = "INTERVIEW_SCHEDULED"
    db.bump(case)
    append_event(case["id"], "STATUS_CHANGE", from_status=prior, to_status="INTERVIEW_SCHEDULED")
    return ok_object(appt, 201)


# ---------- GET /uscis/cases/{id}/interviews --------------------------------

@bp.get("/uscis/cases/<rid>/interviews")
def list_case_interviews(rid: str):
    require_auth(ALL_ROLES)()
    case = lookup_or_404(db.cases, rid, "Case")
    ensure_case_ownership(case, current_role(), current_user_id())
    limit, offset = paginate_params(request.args)
    items = [a for a in db.interviews.values() if a.get("case_id") == rid]
    items.sort(key=lambda a: a.get("created_at", ""))
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


# ---------- GET /uscis/interviews/{id} --------------------------------------

@bp.get("/uscis/interviews/<rid>")
def get_interview(rid: str):
    require_auth(ALL_ROLES)()
    appt = lookup_or_404(db.interviews, rid, "InterviewAppointment")
    return ok_object(appt, 200)


# ---------- POST /uscis/interviews/{id}/complete ----------------------------

@bp.post("/uscis/interviews/<rid>/complete")
def complete_interview(rid: str):
    require_auth(["Officer"])()
    appt = lookup_or_404(db.interviews, rid, "InterviewAppointment")

    if appt.get("status") in ("COMPLETED", "NO_SHOW"):
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Interview already terminal")
    if appt.get("status") != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Interview must be SCHEDULED")
    appt_dt = db.parse_iso_dt(appt["scheduled_at"])
    now_dt = parse_clock_dt()
    if now_dt < appt_dt:
        raise APIError(ERR_INVALID_STATE, 409, "Clock has not reached scheduled_at yet")

    case = db.cases.get(appt["case_id"])
    if case is None or case.get("status") != "INTERVIEW_SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Parent case must be in INTERVIEW_SCHEDULED")

    body = get_json_body()
    require_fields(body, ["decision_after_interview"])
    decision = body["decision_after_interview"]
    require_enum(decision, DECISIONS, "decision_after_interview")

    appt["status"] = "COMPLETED"
    appt["decision_after_interview"] = decision
    db.bump(appt)

    prior = case["status"]
    case["status"] = "INTERVIEW_COMPLETED"
    db.bump(case)
    append_event(case["id"], "INTERVIEW_COMPLETED", payload_json={"decision": decision})
    append_event(case["id"], "STATUS_CHANGE", from_status=prior, to_status="INTERVIEW_COMPLETED")
    return ok_object(appt, 200)


# ---------- POST /uscis/interviews/{id}/mark-no-show ------------------------

@bp.post("/uscis/interviews/<rid>/mark-no-show")
def mark_no_show_interview(rid: str):
    require_auth(["Officer"])()
    appt = lookup_or_404(db.interviews, rid, "InterviewAppointment")

    if appt.get("status") in ("COMPLETED", "NO_SHOW"):
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Interview already terminal")
    if appt.get("status") != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Interview must be SCHEDULED")
    appt_dt = db.parse_iso_dt(appt["scheduled_at"])
    now_dt = parse_clock_dt()
    if now_dt < appt_dt + GRACE_24H:
        raise APIError(ERR_INVALID_STATE, 409, "Grace window has not elapsed")

    appt["status"] = "NO_SHOW"
    db.bump(appt)

    case = db.cases.get(appt["case_id"])
    if case is not None and case.get("status") not in TERMINAL_CASE_STATES:
        prior = case["status"]
        case["status"] = "ABANDONED"
        db.bump(case)
        append_event(case["id"], "STATUS_CHANGE", from_status=prior, to_status="ABANDONED")
    return ok_object(appt, 200)
