"""PMI removal request routes."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
import response
from errors import (
    ApiError,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_STATE,
    ERR_PMI_NOT_ELIGIBLE_HISTORY,
    ERR_PMI_NOT_ELIGIBLE_LTV,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth
from services import calculations as calc
from services import transitions
from services.common import (
    bump,
    new_common_fields,
    get_json_body,
    paginate,
    parse_pagination,
    require_str,
    optional_int,
    sorted_by_created_at,
    strip_internal,
)
from services.lookup import (
    get_pmi_removal_request,
    get_fk_or_404,
    borrower_owns_loan,
    borrower_owns_pmi_request,
)

bp = Blueprint("pmi", __name__)


def _serialize(o: dict) -> dict:
    return strip_internal(o)


# ---------- POST /pmi-removal-requests ----------
@bp.post("/pmi-removal-requests")
@require_auth(roles=["LoanServicer", "Borrower"])
def submit_request():
    body = get_json_body()
    loan_id = require_str(body, "loan_id")
    appraisal_value_cents = optional_int(body, "appraisal_value_cents")

    if appraisal_value_cents is not None and appraisal_value_cents <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, "appraisal_value_cents must be > 0.")

    loan = get_fk_or_404(db.loans, loan_id, name="Loan")

    if g.user_role == "Borrower" and not borrower_owns_loan(loan, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this loan.")

    with db.lock:
        ltv_bps = calc.compute_ltv_bps(loan, appraisal_value_cents)

        r = new_common_fields()
        r["loan_id"] = loan_id
        r["requested_at"] = db.fmt_ts(db.utcnow())
        r["appraisal_value_cents"] = appraisal_value_cents
        r["status"] = "PENDING"
        r["denial_reason"] = "NONE"
        r["computed_ltv_bps"] = ltv_bps
        db.pmi_removal_requests[r["id"]] = r

        # Side effect: loan.pmi_status -> REMOVAL_PENDING (only if currently ACTIVE)
        if loan.get("pmi_status") == "ACTIVE":
            loan["pmi_status"] = "REMOVAL_PENDING"
            bump(loan)

    return response.ok(_serialize(r), status=201)


# ---------- GET /pmi-removal-requests ----------
@bp.get("/pmi-removal-requests")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def list_requests():
    limit, offset = parse_pagination()
    loan_id = request.args.get("loan_id")
    status_filter = request.args.get("status")
    items = list(db.pmi_removal_requests.values())
    if loan_id is not None:
        items = [r for r in items if r.get("loan_id") == loan_id]
    if status_filter is not None:
        items = [r for r in items if r.get("status") == status_filter]
    if g.user_role == "Borrower":
        items = [r for r in items if borrower_owns_pmi_request(r, g.user_id)]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([_serialize(x) for x in page], limit, offset, total)


# ---------- GET /pmi-removal-requests/{id} ----------
@bp.get("/pmi-removal-requests/<rid>")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def read_request(rid: str):
    r = get_pmi_removal_request(rid)
    if g.user_role == "Borrower" and not borrower_owns_pmi_request(r, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this request.")
    return response.ok(_serialize(r))


# ---------- POST /pmi-removal-requests/{id}/decide ----------
@bp.post("/pmi-removal-requests/<rid>/decide")
@require_auth(roles=["ComplianceOfficer"])
def decide_request(rid: str):
    r = get_pmi_removal_request(rid)
    if r.get("status") != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Request must be PENDING to decide.")

    loan = db.loans.get(r.get("loan_id"))
    if loan is None:
        raise ApiError(ERR_INVALID_STATE, "Underlying loan is missing.")

    with db.lock:
        # Re-run eligibility
        ltv_bps = calc.compute_ltv_bps(loan, r.get("appraisal_value_cents"))
        r["computed_ltv_bps"] = ltv_bps

        denial_reason = calc.pmi_denial_reason(loan, ltv_bps)

        if denial_reason is None:
            # APPROVE
            r["status"] = "APPROVED"
            r["denial_reason"] = "NONE"
            bump(r)
            loan["pmi_required"] = False
            loan["pmi_status"] = "REMOVED"
            transitions.recompute_total_monthly_payment(loan)
            bump(loan)
            return response.ok(_serialize(r))
        else:
            # DENY — set denial_reason, revert pmi_status to ACTIVE.
            # Per PRD §4 the decide endpoint returns 200 OK; the denial reason
            # is conveyed via the request's `denial_reason` field.
            r["status"] = "DENIED"
            r["denial_reason"] = denial_reason
            bump(r)
            if loan.get("pmi_status") == "REMOVAL_PENDING":
                loan["pmi_status"] = "ACTIVE"
            bump(loan)
            return response.ok(_serialize(r))
