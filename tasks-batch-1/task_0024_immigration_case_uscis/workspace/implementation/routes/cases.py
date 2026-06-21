"""Case CRUD + file + advance-review + decide + visa-availability + events."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_CASE_TYPE_NOT_APPLICABLE,
    ERR_VISA_RETROGRESSED,
    ERR_STALE_VERSION,
    ERR_REFERENCED_NOT_FOUND,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields,
    require_enum,
    require_string,
    lookup_or_404,
    lookup_fk_or_referenced,
    ensure_case_ownership,
    evaluation_month_from_clock,
)
from services.events import append_event
from services.calculations import (
    compute_filing_fee_cents,
    compute_is_under_14,
    evaluate_visa_availability,
    TERMINAL_CASE_STATES,
)


bp = Blueprint("cases", __name__)


CASE_TYPES = {"I-130", "I-485", "I-765", "I-131"}
PREFERENCE_CHOICES = {"F1", "F2A", "F2B", "F3", "F4", "IR"}
CASE_STATUSES = {
    "DRAFT", "FILED", "BIOMETRICS_SCHEDULED", "BIOMETRICS_COMPLETED",
    "UNDER_REVIEW", "RFE_PENDING", "INTERVIEW_SCHEDULED",
    "INTERVIEW_COMPLETED", "APPROVED", "DENIED", "ABANDONED",
}
ALL_ROLES = ["Applicant", "Attorney", "Officer", "FieldOfficeAdmin"]


# ---------- POST /uscis/cases ------------------------------------------------

@bp.post("/uscis/cases")
def create_case():
    require_auth(["Applicant", "Attorney"])()
    body = get_json_body()
    require_fields(body, ["applicant_id", "case_type"])
    applicant_id = body["applicant_id"]
    case_type = body["case_type"]
    attorney_id = body.get("attorney_id")
    preference_category = body.get("preference_category")

    require_string(applicant_id, "applicant_id")
    require_enum(case_type, CASE_TYPES, "case_type")

    # FK existence (post-auth, pre-business)
    applicant = lookup_fk_or_referenced(db.applicants, applicant_id, "Applicant")
    if attorney_id is not None:
        require_string(attorney_id, "attorney_id")
        lookup_fk_or_referenced(db.attorneys, attorney_id, "Attorney")

    # Required preference_category for I-130 (validated at create time too).
    # For non-I-130 case types, preference_category is OPTIONAL — but if supplied it
    # must be a valid enum value (PRD §3.5 references "an I-485 case whose
    # `preference_category` is set" for the visa-availability gate, so the field
    # must be storable on I-485 / I-765 / I-131 as well).
    if case_type == "I-130":
        if preference_category is None:
            raise APIError(ERR_INVALID_REQUEST, 400, "preference_category is required for I-130")
        require_enum(preference_category, PREFERENCE_CHOICES, "preference_category")
    else:
        if preference_category is not None:
            require_enum(preference_category, PREFERENCE_CHOICES, "preference_category")

    # Ownership check: an Applicant creating a case must reference themselves.
    role = current_role()
    user_id = current_user_id()
    if role == "Applicant" and applicant_id != user_id:
        from errors import ERR_OWNERSHIP_VIOLATION
        raise APIError(ERR_OWNERSHIP_VIOLATION, 403, "Applicant can only create cases for themselves")
    if role == "Attorney":
        if attorney_id is None or attorney_id != user_id:
            from errors import ERR_OWNERSHIP_VIOLATION
            raise APIError(ERR_OWNERSHIP_VIOLATION, 403, "Attorney must be the attorney_of_record on this case")

    case = {
        "applicant_id": applicant_id,
        "attorney_id": attorney_id,
        "case_type": case_type,
        "preference_category": preference_category,
        "receipt_number": None,
        "priority_date": None,
        "file_date": None,
        "status": "DRAFT",
        "filing_fee_cents": None,
        "rfe_round_count": 0,
        "assigned_officer_id": None,
    }
    db.stamp_common(case)
    db.cases[case["id"]] = case
    return ok_object(case, 201)


# ---------- GET /uscis/cases/{id} -------------------------------------------

@bp.get("/uscis/cases/<rid>")
def get_case(rid: str):
    require_auth(ALL_ROLES)()
    case = lookup_or_404(db.cases, rid, "Case")
    ensure_case_ownership(case, current_role(), current_user_id())
    return ok_object(case, 200)


# ---------- GET /uscis/cases -------------------------------------------------

@bp.get("/uscis/cases")
def list_cases():
    require_auth(["Officer", "FieldOfficeAdmin"])()
    limit, offset = paginate_params(request.args)

    applicant_id = request.args.get("applicant_id")
    attorney_id = request.args.get("attorney_id")
    assigned_officer_id = request.args.get("assigned_officer_id")
    status = request.args.get("status")
    case_type = request.args.get("case_type")

    items = list(db.cases.values())
    if applicant_id is not None:
        items = [c for c in items if c.get("applicant_id") == applicant_id]
    if attorney_id is not None:
        items = [c for c in items if c.get("attorney_id") == attorney_id]
    if assigned_officer_id is not None:
        items = [c for c in items if c.get("assigned_officer_id") == assigned_officer_id]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    if case_type is not None:
        items = [c for c in items if c.get("case_type") == case_type]

    items.sort(key=lambda c: c.get("created_at", ""))
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


# ---------- POST /uscis/cases/{id}/file --------------------------------------

@bp.post("/uscis/cases/<rid>/file")
def file_case(rid: str):
    require_auth(["Applicant", "Attorney"])()
    case = lookup_or_404(db.cases, rid, "Case")
    ensure_case_ownership(case, current_role(), current_user_id())

    if case.get("status") in TERMINAL_CASE_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Case is already terminal")
    if case.get("status") != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Case must be in DRAFT")

    # I-130 needs preference_category — already enforced at create; re-check defensively.
    case_type = case.get("case_type")
    if case_type == "I-130" and case.get("preference_category") not in PREFERENCE_CHOICES:
        raise APIError(ERR_INVALID_REQUEST, 400, "preference_category required for I-130")

    # FK existence: applicant must still exist (defensive — it can't be deleted, but spec says check it).
    applicant = lookup_fk_or_referenced(db.applicants, case.get("applicant_id"), "Applicant")

    file_date = db.get_current_utc()[:10]  # YYYY-MM-DD portion of logical clock

    # Recompute is_under_14 against file_date.
    is_under_14 = compute_is_under_14(applicant["date_of_birth"], file_date)
    applicant["is_under_14"] = is_under_14
    db.bump(applicant)

    fee_cents = compute_filing_fee_cents(case_type, is_under_14)
    officer_id = db.round_robin_officer()
    receipt = db.mint_receipt_number(file_date)

    prior_status = case["status"]
    case["receipt_number"] = receipt
    case["file_date"] = file_date
    case["priority_date"] = file_date
    case["filing_fee_cents"] = fee_cents
    case["assigned_officer_id"] = officer_id
    case["status"] = "FILED"
    db.bump(case)

    append_event(case["id"], "STATUS_CHANGE", from_status=prior_status, to_status="FILED")
    append_event(case["id"], "FEE_ASSESSED", payload_json={"fee_cents": fee_cents})
    append_event(case["id"], "OFFICER_ASSIGNED", payload_json={"officer_id": officer_id})

    return ok_object(case, 200)


# ---------- POST /uscis/cases/{id}/advance-review ---------------------------

@bp.post("/uscis/cases/<rid>/advance-review")
def advance_review(rid: str):
    require_auth(["Officer"])()
    case = lookup_or_404(db.cases, rid, "Case")

    if case.get("status") in TERMINAL_CASE_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Case is already terminal")

    status = case.get("status")
    case_type = case.get("case_type")

    # Two branches:
    #   FILED + I-130 -> UNDER_REVIEW (skips biometrics)
    #   BIOMETRICS_COMPLETED (any case type) -> UNDER_REVIEW
    if status == "BIOMETRICS_COMPLETED":
        pass  # any case type allowed
    elif status == "FILED":
        if case_type != "I-130":
            # I-485/I-765/I-131 must go through biometrics first.
            raise APIError(
                ERR_CASE_TYPE_NOT_APPLICABLE,
                422,
                "advance-review from FILED applies only to I-130",
            )
    else:
        raise APIError(ERR_INVALID_STATE, 409, f"Case must be in FILED or BIOMETRICS_COMPLETED (was {status})")

    prior_status = status
    case["status"] = "UNDER_REVIEW"
    db.bump(case)
    append_event(case["id"], "STATUS_CHANGE", from_status=prior_status, to_status="UNDER_REVIEW")
    return ok_object(case, 200)


# ---------- POST /uscis/cases/{id}/decide -----------------------------------

@bp.post("/uscis/cases/<rid>/decide")
def decide_case(rid: str):
    require_auth(["Officer"])()
    case = lookup_or_404(db.cases, rid, "Case")

    if case.get("status") in TERMINAL_CASE_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Case is already terminal")

    status = case.get("status")
    # Only UNDER_REVIEW and INTERVIEW_COMPLETED can be decided.
    if status not in ("UNDER_REVIEW", "INTERVIEW_COMPLETED"):
        raise APIError(ERR_INVALID_STATE, 409, f"Cannot decide from {status}")

    # Case-type applicability for the UNDER_REVIEW branch:
    if status == "UNDER_REVIEW":
        if case.get("case_type") == "I-485":
            # I-485 must route through interview.
            raise APIError(
                ERR_CASE_TYPE_NOT_APPLICABLE,
                422,
                "I-485 must be decided via the interview path",
            )
        # No open RFE check applies here.
        for rfe in db.rfes.values():
            if rfe.get("case_id") == case["id"] and rfe.get("status") == "ISSUED":
                # An open RFE on UNDER_REVIEW shouldn't happen (the case would be RFE_PENDING),
                # but defensively guard.
                raise APIError(ERR_INVALID_STATE, 409, "Cannot decide while RFE is open")

    # Read body AFTER state checks (priority §2.11 places ERR_INVALID_REQUEST last).
    body = get_json_body()
    require_fields(body, ["decision", "expected_case_version"])
    decision = body["decision"]
    expected_version = body["expected_case_version"]

    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        # OCC mismatch reading should still rank as ERR_INVALID_REQUEST per priority,
        # but it's safer to fail this with INVALID_REQUEST.
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_case_version must be integer")

    # Determine allowed decisions per branch.
    if status == "UNDER_REVIEW":
        if decision not in ("APPROVE", "DENY"):
            raise APIError(ERR_INVALID_REQUEST, 400, "decision must be APPROVE or DENY from UNDER_REVIEW")
    else:  # INTERVIEW_COMPLETED
        if decision not in ("APPROVE", "DENY", "REOPEN"):
            raise APIError(ERR_INVALID_REQUEST, 400, "decision must be APPROVE, DENY, or REOPEN")
        # Need latest interview's decision_after_interview consistent with the requested decision.
        # (See §3.7.)
        latest_interview = _latest_interview_for_case(case["id"])
        if decision == "APPROVE":
            if not latest_interview or latest_interview.get("decision_after_interview") != "APPROVE":
                raise APIError(ERR_INVALID_STATE, 409, "Latest interview must have decision APPROVE")
        elif decision == "REOPEN":
            if not latest_interview or latest_interview.get("decision_after_interview") != "NEEDS_REVIEW":
                raise APIError(ERR_INVALID_STATE, 409, "Latest interview must have decision NEEDS_REVIEW to REOPEN")
        # For DENY, no constraint on latest_interview.decision_after_interview.

    # Visa-availability gate for I-485 approvals (both branches).
    if decision == "APPROVE" and case.get("case_type") == "I-485":
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
                raise APIError(ERR_VISA_RETROGRESSED, 422, "Visa unavailable for I-485 at evaluation month")

    # OCC check — last per priority §2.11.
    if expected_version != case.get("version"):
        raise APIError(ERR_STALE_VERSION, 412, "Case version has advanced")

    prior_status = status
    if decision == "APPROVE":
        new_status = "APPROVED"
    elif decision == "DENY":
        new_status = "DENIED"
    else:  # REOPEN
        new_status = "UNDER_REVIEW"

    case["status"] = new_status
    db.bump(case)
    append_event(case["id"], "STATUS_CHANGE", from_status=prior_status, to_status=new_status)
    return ok_object(case, 200)


def _latest_interview_for_case(case_id: str) -> Optional[dict]:
    interviews = [i for i in db.interviews.values() if i.get("case_id") == case_id]
    if not interviews:
        return None
    interviews.sort(key=lambda i: i.get("created_at", ""), reverse=True)
    return interviews[0]


# ---------- GET /uscis/cases/{id}/events ------------------------------------

@bp.get("/uscis/cases/<rid>/events")
def list_case_events(rid: str):
    require_auth(ALL_ROLES)()
    case = lookup_or_404(db.cases, rid, "Case")
    ensure_case_ownership(case, current_role(), current_user_id())
    limit, offset = paginate_params(request.args)

    items = [e for e in db.case_events.values() if e.get("case_id") == rid]
    items.sort(key=lambda e: e.get("created_at", ""))
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


# ---------- GET /uscis/cases/{id}/visa-availability -------------------------

@bp.get("/uscis/cases/<rid>/visa-availability")
def case_visa_availability(rid: str):
    require_auth(ALL_ROLES)()
    case = lookup_or_404(db.cases, rid, "Case")
    ensure_case_ownership(case, current_role(), current_user_id())

    applicant = db.applicants.get(case.get("applicant_id"))
    eval_month = evaluation_month_from_clock()

    # Need priority_date and preference_category to compute meaningfully.
    if case.get("priority_date") is None or case.get("preference_category") is None or applicant is None:
        # Without these the case has no visa availability concept — return RETROGRESSED
        # (visa unavailable) as the conservative default.
        return ok_object(
            {
                "final_action": "RETROGRESSED",
                "filing_date": "RETROGRESSED",
                "evaluation_month": eval_month,
            },
            200,
        )

    final_action = evaluate_visa_availability(
        priority_date_iso=case["priority_date"],
        preference_category=case["preference_category"],
        country=applicant["country_of_chargeability"],
        chart_type="FINAL_ACTION",
        evaluation_month=eval_month,
        visa_bulletin_store=db.visa_bulletin,
    )
    filing_date = evaluate_visa_availability(
        priority_date_iso=case["priority_date"],
        preference_category=case["preference_category"],
        country=applicant["country_of_chargeability"],
        chart_type="FILING_DATE",
        evaluation_month=eval_month,
        visa_bulletin_store=db.visa_bulletin,
    )
    return ok_object(
        {
            "final_action": final_action,
            "filing_date": filing_date,
            "evaluation_month": eval_month,
        },
        200,
    )
