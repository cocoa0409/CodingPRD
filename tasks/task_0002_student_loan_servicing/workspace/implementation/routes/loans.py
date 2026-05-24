"""Loan endpoints + nested servicing-events and delinquency-records."""
from __future__ import annotations

import re

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_DEFAULT_THRESHOLD_NOT_MET,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import current_role, current_user_id, require_roles
from response import success, success_list
from routes._common import (
    borrower_owns_loan,
    borrower_ownership_check,
    get_field,
    must_get,
    paginate_sorted,
    parse_json_body,
    parse_pagination,
)
from services import loan_ops, serializer

bp = Blueprint("loans", __name__)


VALID_LOAN_TYPES = {"DIRECT_SUBSIDIZED", "DIRECT_UNSUBSIDIZED", "DIRECT_PLUS"}
VALID_EVENT_TYPES = {
    "GRACE_BEGIN",
    "REPAYMENT_BEGIN",
    "DEFERMENT_BEGIN",
    "DEFERMENT_END",
    "FORBEARANCE_BEGIN",
    "FORBEARANCE_END",
    "DELINQUENT_BEGIN",
    "REPAYMENT_RESUME",
    "DEFAULT_DECLARED",
    "CAPITALIZATION",
    "RECERTIFY_IDR",
}
VALID_REASON_CODES = {
    "SCHOOL_ENROLLMENT",
    "ECONOMIC_HARDSHIP",
    "MILITARY_SERVICE",
    "MEDICAL",
    "NATURAL_DISASTER",
    "ADMIN_FORBEARANCE",
    "GRACE_EXPIRY",
    "MISSED_PAYMENTS_270D",
    "IDR_ANNUAL_RECERT",
    "OTHER",
}
DEFERMENT_REASONS = {"SCHOOL_ENROLLMENT", "ECONOMIC_HARDSHIP", "MILITARY_SERVICE", "MEDICAL"}
FORBEARANCE_REASONS = {"ECONOMIC_HARDSHIP", "NATURAL_DISASTER", "ADMIN_FORBEARANCE", "MEDICAL"}


@bp.post("/v1/loans")
@require_roles({"LoanServicer"})
def create_loan():
    body = parse_json_body()
    borrower_id = get_field(body, "borrower_id")
    loan_type = get_field(body, "loan_type")
    original_principal_cents = get_field(body, "original_principal_cents")
    interest_rate_bps = get_field(body, "interest_rate_bps")
    disbursement_date = get_field(body, "disbursement_date")

    must_get(db.borrowers, borrower_id, "Borrower")
    if loan_type not in VALID_LOAN_TYPES:
        raise APIError(ERR_INVALID_REQUEST, "Invalid loan_type")
    if not isinstance(original_principal_cents, int) or isinstance(original_principal_cents, bool):
        raise APIError(ERR_INVALID_REQUEST, "original_principal_cents must be int")
    if original_principal_cents < 1 or original_principal_cents > 200_000_000:
        raise APIError(ERR_INVALID_REQUEST, "original_principal_cents out of range")
    if not isinstance(interest_rate_bps, int) or isinstance(interest_rate_bps, bool):
        raise APIError(ERR_INVALID_REQUEST, "interest_rate_bps must be int")
    if interest_rate_bps < 0 or interest_rate_bps > 5000:
        raise APIError(ERR_INVALID_REQUEST, "interest_rate_bps out of range")
    if not isinstance(disbursement_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", disbursement_date):
        raise APIError(ERR_INVALID_REQUEST, "disbursement_date must be YYYY-MM-DD")

    lid = db.new_id()
    now = db.now_iso()
    loan = {
        "id": lid,
        "borrower_id": borrower_id,
        "loan_type": loan_type,
        "original_principal_cents": original_principal_cents,
        "outstanding_principal_cents": original_principal_cents,
        "accrued_interest_cents": 0,
        "interest_rate_bps": interest_rate_bps,
        "disbursement_date": disbursement_date,
        "status": "IN_SCHOOL",
        "days_delinquent": 0,
        "capitalized_interest_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.loans[lid] = loan
    serializer.recompute_borrower(borrower_id)
    return success(serializer.serialize_loan(loan), status=201)


@bp.get("/v1/loans/<loan_id>")
@require_roles({"LoanServicer", "PSLFAdjudicator", "VADischargeOfficer", "Borrower"})
def get_loan(loan_id):
    l = must_get(db.loans, loan_id, "Loan")
    if current_role() == "Borrower" and l["borrower_id"] != current_user_id():
        raise APIError(ERR_NOT_RESOURCE_OWNER, "Borrower does not own this loan")
    return success(serializer.serialize_loan(l), status=200)


@bp.get("/v1/loans")
@require_roles({"LoanServicer", "PSLFAdjudicator", "VADischargeOfficer", "Borrower"})
def list_loans():
    limit, offset = parse_pagination()
    borrower_filter = request.args.get("borrower_id")
    status_filter = request.args.get("status")

    items = list(db.loans.values())
    if current_role() == "Borrower":
        items = [l for l in items if l["borrower_id"] == current_user_id()]
    if borrower_filter:
        items = [l for l in items if l["borrower_id"] == borrower_filter]
    if status_filter:
        items = [l for l in items if l["status"] == status_filter]

    items.sort(key=lambda l: l["created_at"])
    page, total = paginate_sorted(items, limit, offset)
    return success_list([serializer.serialize_loan(l) for l in page], limit, offset, total)


# ---------- ServicingEvents ----------


@bp.post("/v1/loans/<loan_id>/servicing-events")
@require_roles({"LoanServicer"})
def create_servicing_event(loan_id):
    loan = must_get(db.loans, loan_id, "Loan")
    body = parse_json_body()
    event_type = get_field(body, "event_type")
    effective_on = get_field(body, "effective_on")
    reason_code = get_field(body, "reason_code")

    if event_type not in VALID_EVENT_TYPES:
        raise APIError(ERR_INVALID_REQUEST, "Invalid event_type")
    if reason_code not in VALID_REASON_CODES:
        raise APIError(ERR_INVALID_REQUEST, "Invalid reason_code")
    if not isinstance(effective_on, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective_on):
        raise APIError(ERR_INVALID_REQUEST, "effective_on must be YYYY-MM-DD")

    # State preconditions per §1.2 Loan machine
    actor = current_user_id()
    status = loan["status"]
    create_record = True
    if event_type == "GRACE_BEGIN":
        if status != "IN_SCHOOL":
            raise APIError(ERR_INVALID_STATE, "GRACE_BEGIN requires IN_SCHOOL")
        if effective_on < loan["disbursement_date"]:
            raise APIError(ERR_INVALID_STATE, "effective_on before disbursement_date")
        loan_ops.transition_grace(loan, effective_on, actor)
    elif event_type == "REPAYMENT_BEGIN":
        if status != "GRACE":
            raise APIError(ERR_INVALID_STATE, "REPAYMENT_BEGIN requires GRACE")
        loan_ops.transition_grace_to_repayment(loan, effective_on, actor)
    elif event_type == "DEFERMENT_BEGIN":
        if status != "REPAYMENT":
            raise APIError(ERR_INVALID_STATE, "DEFERMENT_BEGIN requires REPAYMENT")
        if reason_code not in DEFERMENT_REASONS:
            raise APIError(ERR_INVALID_STATE, "Invalid reason for DEFERMENT_BEGIN")
        if serializer.open_delinquency_for_loan(loan["id"]):
            raise APIError(ERR_INVALID_STATE, "Cannot defer with open delinquency")
        loan_ops.transition_to_deferment(loan, effective_on, actor)
    elif event_type == "DEFERMENT_END":
        if status != "DEFERMENT":
            raise APIError(ERR_INVALID_STATE, "DEFERMENT_END requires DEFERMENT")
        loan_ops.transition_deferment_to_repayment(loan, effective_on, actor)
    elif event_type == "FORBEARANCE_BEGIN":
        if status not in {"REPAYMENT", "DELINQUENT"}:
            raise APIError(ERR_INVALID_STATE, "FORBEARANCE_BEGIN requires REPAYMENT or DELINQUENT")
        if reason_code not in FORBEARANCE_REASONS:
            raise APIError(ERR_INVALID_STATE, "Invalid reason for FORBEARANCE_BEGIN")
        loan_ops.transition_to_forbearance(loan, effective_on, actor, reason_code)
    elif event_type == "FORBEARANCE_END":
        if status != "FORBEARANCE":
            raise APIError(ERR_INVALID_STATE, "FORBEARANCE_END requires FORBEARANCE")
        loan_ops.transition_forbearance_to_repayment(loan, effective_on, actor)
    elif event_type == "DEFAULT_DECLARED":
        if status != "DELINQUENT":
            raise APIError(ERR_INVALID_STATE, "DEFAULT_DECLARED requires DELINQUENT")
        rec = serializer.open_delinquency_for_loan(loan["id"])
        if rec is None or rec["cumulative_days"] < 270:
            raise APIError(ERR_DEFAULT_THRESHOLD_NOT_MET, "DelinquencyRecord.cumulative_days < 270")
        loan_ops.transition_to_default(loan, effective_on, actor, reason_code)
    elif event_type == "CAPITALIZATION":
        # Explicit capitalization: apply to the loan in any non-terminal state
        if status in {"PAID_OFF", "DEFAULT", "DISCHARGED"}:
            raise APIError(ERR_INVALID_STATE, "Cannot capitalize a terminal loan")
        # We do the cap inline. capitalize_interest already emits the event itself,
        # so to avoid duplicating we'll do the work manually here.
        capitalizable = loan["accrued_interest_cents"]
        loan["outstanding_principal_cents"] += capitalizable
        loan["capitalized_interest_cents"] += capitalizable
        loan["accrued_interest_cents"] = 0
        serializer.bump_loan(loan)
        serializer.recompute_borrower(loan["borrower_id"])
    elif event_type == "RECERTIFY_IDR":
        # Recertify-IDR as a free-form audit event: don't change loan status; just record.
        # Bump version per audit convention.
        serializer.bump_loan(loan)
    elif event_type == "DELINQUENT_BEGIN":
        # System-only — clients usually drive via clock advance. Reject from servicer.
        raise APIError(ERR_INVALID_STATE, "DELINQUENT_BEGIN is system-driven")
    elif event_type == "REPAYMENT_RESUME":
        # Generic resume — only meaningful from DEFERMENT/FORBEARANCE; treat as alias.
        if status == "DEFERMENT":
            loan_ops.transition_deferment_to_repayment(loan, effective_on, actor)
        elif status == "FORBEARANCE":
            loan_ops.transition_forbearance_to_repayment(loan, effective_on, actor)
        else:
            raise APIError(ERR_INVALID_STATE, "REPAYMENT_RESUME requires DEFERMENT or FORBEARANCE")
    else:
        raise APIError(ERR_INVALID_STATE, f"Unsupported event_type: {event_type}")

    # Record the event (only the user-driven event, never the system CAPITALIZATION twins
    # which transition_grace_to_repayment etc. already inserted).
    eid = db.new_id()
    event = {
        "id": eid,
        "loan_id": loan_id,
        "event_type": event_type,
        "effective_on": effective_on,
        "reason_code": reason_code,
        "created_by_user_id": actor,
        "created_at": db.now_iso(),
    }
    db.servicing_events[eid] = event
    return success(serializer.serialize_event(event), status=201)


@bp.get("/v1/loans/<loan_id>/servicing-events")
@require_roles({"LoanServicer", "PSLFAdjudicator", "VADischargeOfficer", "Borrower"})
def list_servicing_events(loan_id):
    must_get(db.loans, loan_id, "Loan")
    borrower_owns_loan(loan_id)
    limit, offset = parse_pagination()
    items = [e for e in db.servicing_events.values() if e["loan_id"] == loan_id]
    # chronological by effective_on, then created_at
    items.sort(key=lambda e: (e["effective_on"], e["created_at"]))
    page, total = paginate_sorted(items, limit, offset)
    return success_list([serializer.serialize_event(e) for e in page], limit, offset, total)


# ---------- DelinquencyRecords ----------


@bp.get("/v1/loans/<loan_id>/delinquency-records")
@require_roles({"LoanServicer", "PSLFAdjudicator", "Borrower"})
def list_delinquency_records(loan_id):
    must_get(db.loans, loan_id, "Loan")
    borrower_owns_loan(loan_id)
    limit, offset = parse_pagination()
    outcome_filter = request.args.get("outcome")
    items = [d for d in db.delinquency_records.values() if d["loan_id"] == loan_id]
    if outcome_filter:
        items = [d for d in items if d["outcome"] == outcome_filter]
    # most recent first by opened_on (desc); tie-break created_at ASC
    items.sort(key=lambda d: (d["created_at"],))  # secondary asc
    items.sort(key=lambda d: d["opened_on"], reverse=True)
    page, total = paginate_sorted(items, limit, offset)
    return success_list([serializer.serialize_delinquency(d) for d in page], limit, offset, total)
