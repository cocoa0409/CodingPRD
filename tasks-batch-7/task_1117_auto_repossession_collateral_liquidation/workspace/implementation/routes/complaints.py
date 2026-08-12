"""Borrower complaints and the restitution cascade (PRD §3.8)."""
from flask import Blueprint

from db import store, base_fields, touch, get_or_404, sorted_all
from errors import (
    ApiError, ERR_INVALID_CASE_STATE, ERR_INVALID_COMPLAINT_STATE,
    ERR_FORBIDDEN_OWNERSHIP, ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from serializers import complaint_out
from services.transitions import restitution_cascade
from util import validate_body

bp = Blueprint("complaints", __name__)

COMPLAINT_CATEGORIES = {
    "WRONGFUL_REPOSSESSION", "BREACH_OF_PEACE", "PROPERTY_LOSS",
    "DEFICIENCY_DISPUTE", "NOTICE_DEFECT",
}

COMPLAINT_ELIGIBLE_STATES = {
    "REPO_ACTIVE", "COLLATERAL_SECURED", "REDEMPTION_OPEN",
    "CONSIGNMENT_PENDING", "IN_AUCTION", "SALE_CONFIRMED", "DEFICIENCY_NOTICED",
}

OUTCOMES = {"UPHELD", "DISMISSED"}


@bp.post("/recovery-cases/<cid>/complaints")
def file_complaint(cid):
    user_id, _role = require_roles("Borrower")
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    loan = store.loan_accounts[case["loan_account_id"]]
    if loan["borrower_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Caller does not own the target case")
    body = validate_body({
        "category": ("str", True, COMPLAINT_CATEGORIES),
        "description": ("str", True, None),
    })
    if case["status"] not in COMPLAINT_ELIGIBLE_STATES:
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit a complaint")
    complaint = base_fields()
    complaint.update({
        "recovery_case_id": case["id"],
        "borrower_id": user_id,
        "category": body["category"],
        "description": body["description"],
        "status": "UNDER_REVIEW",
        "resolved_by_user_id": None,
        "_seq": store.next_seq(),
    })
    store.complaints[complaint["id"]] = complaint
    # Filing freezes the case; a LISTED consignment is withdrawn atomically.
    case["pre_complaint_state"] = case["status"]
    case["status"] = "COMPLAINT_REVIEW"
    touch(case)
    for c in store.consignments.values():
        if c["recovery_case_id"] == case["id"] and c["status"] == "LISTED":
            c["status"] = "WITHDRAWN"
            touch(c)
    return object_response(complaint_out(complaint), 201)


@bp.get("/recovery-cases/<cid>/complaints")
def list_case_complaints(cid):
    require_roles(*ALL_ROLES)
    get_or_404(store.recovery_cases, cid, "RecoveryCase")
    rows = [c for c in sorted_all(store.complaints)
            if c["recovery_case_id"] == cid]
    return list_response(rows, complaint_out)


@bp.post("/complaints/<cid>/resolve")
def resolve_complaint(cid):
    user_id, _role = require_roles("ComplianceOfficer")
    complaint = get_or_404(store.complaints, cid, "Complaint")
    body = validate_body({
        "outcome": ("str", True, OUTCOMES),
    })
    if complaint["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_COMPLAINT_STATE, 409,
                       f"Complaint status {complaint['status']} does not permit resolve")
    case = store.recovery_cases[complaint["recovery_case_id"]]
    if user_id == case["opened_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "The case opener may not resolve its complaint")
    if body["outcome"] == "DISMISSED":
        complaint["status"] = "DISMISSED"
        complaint["resolved_by_user_id"] = user_id
        touch(complaint)
        # Restore the case verbatim to its pre-complaint state.
        case["status"] = case["pre_complaint_state"]
        touch(case)
    else:
        restitution_cascade(case, complaint, user_id)
    return object_response(complaint_out(complaint))
