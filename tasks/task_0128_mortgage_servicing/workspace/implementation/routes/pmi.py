"""PMI removal request routes."""
from __future__ import annotations

from flask import Blueprint, g

from config import AUTO_TERM_LTV_BPS, BORROWER_REQ_LTV_BPS, PMI_HISTORY_MONTHS
from db import store
from errors import (
    ApiError,
    err_forbidden,
    err_invalid_state,
    err_pmi_history,
    err_pmi_ltv,
    err_resource_not_found,
)
from middleware import require_auth
from response import success
from services.calculations import evaluate_ltv_bps
from services.loan_engine import bump
from services.serializers import pmi_request_view
from utils import add_months, midnight_utc, new_uuid

from routes._helpers import (
    enforce_borrower_owns_loan,
    get_int,
    get_json,
    get_loan_or_404,
)

bp = Blueprint("pmi", __name__)

_ALLOWED_TRIGGERS = {"BORROWER_REQUEST", "AUTO_TERMINATION"}
_ALLOWED_DENIAL_REASONS = {"LTV_TOO_HIGH", "PAYMENT_HISTORY_INSUFFICIENT", "LOAN_NOT_CURRENT"}


@bp.post("/loans/<lid>/pmi-removal-requests")
@require_auth(["Servicer", "Borrower"])
def create_pmi_request(lid):
    loan = get_loan_or_404(lid)
    enforce_borrower_owns_loan(loan)
    if loan["pmi_status"] != "ACTIVE":
        raise err_invalid_state("PMI removal is only valid when pmi_status is ACTIVE.")
    body = get_json()
    trigger = body.get("trigger")
    if trigger not in _ALLOWED_TRIGGERS:
        raise err_invalid_state("Invalid trigger.")
    # Borrowers may only file BORROWER_REQUEST.
    if g.role == "Borrower" and trigger != "BORROWER_REQUEST":
        raise err_forbidden("Borrower may only file BORROWER_REQUEST.")
    if trigger == "BORROWER_REQUEST":
        appraised = get_int(body, "current_appraised_value_cents")
        if appraised is None or appraised <= 0:
            raise err_invalid_state("current_appraised_value_cents must be > 0 for BORROWER_REQUEST.")
        basis = appraised
    else:
        appraised = None
        basis = loan["original_appraised_value_cents"]
    ltv_bps = evaluate_ltv_bps(loan["principal_balance_cents"], basis)

    now = store.now()
    rid = new_uuid()
    record = {
        "id": rid,
        "loan_id": lid,
        "trigger": trigger,
        "current_appraised_value_cents": appraised,
        "evaluated_ltv_bps": ltv_bps,
        "decision": "PENDING",
        "denial_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.pmi_requests[rid] = record
    loan["pmi_status"] = "REMOVAL_REQUESTED"
    bump(loan, now)
    return success(pmi_request_view(record), 201)


def _has_late_payment_in_last_24_months(loan: dict) -> bool:
    """True if any POSTED payment in the last 24 scheduled months was late."""
    cutoff = add_months(loan["next_due_date"], -PMI_HISTORY_MONTHS)
    for p in store.payments.values():
        if p["loan_id"] != loan["id"] or p["status"] != "POSTED":
            continue
        if midnight_utc(p["received_date"]) < midnight_utc(cutoff):
            continue
        # We have to guess the "scheduled due date" against which this payment
        # was posted. Conservative rule: if any allocation_late_fee_cents > 0
        # then the payment was late; OR if received_date > recorded
        # next_due_date at posting time we have no way of knowing.  Use the
        # late-fee marker as the principal signal.
        if p["allocation_late_fee_cents"] > 0:
            return True
    return False


@bp.post("/loans/<lid>/pmi-removal-requests/<rid>/approve")
@require_auth(["PmiUnderwriter"])
def approve_pmi(lid, rid):
    loan = get_loan_or_404(lid)
    req = store.pmi_requests.get(rid)
    if req is None or req["loan_id"] != lid:
        raise err_resource_not_found("PmiRemovalRequest not found under loan.")
    if req["decision"] != "PENDING":
        raise err_invalid_state("Only PENDING requests can be approved.")

    # LTV threshold (priority 17).
    if req["trigger"] == "BORROWER_REQUEST":
        if req["evaluated_ltv_bps"] > BORROWER_REQ_LTV_BPS:
            raise err_pmi_ltv()
    else:
        if req["evaluated_ltv_bps"] > AUTO_TERM_LTV_BPS:
            raise err_pmi_ltv()

    # History check (priority 18) — only for BORROWER_REQUEST.
    if req["trigger"] == "BORROWER_REQUEST":
        if loan["posture"] != "CURRENT":
            raise err_pmi_history()
        if _has_late_payment_in_last_24_months(loan):
            raise err_pmi_history()

    now = store.now()
    req["decision"] = "APPROVED"
    bump(req, now)
    if req["trigger"] == "BORROWER_REQUEST":
        loan["pmi_status"] = "REMOVED"
    else:
        loan["pmi_status"] = "AUTO_TERMINATED"
    loan["pmi_monthly_cents"] = 0
    bump(loan, now)
    return success(pmi_request_view(req), 200)


@bp.post("/loans/<lid>/pmi-removal-requests/<rid>/deny")
@require_auth(["PmiUnderwriter"])
def deny_pmi(lid, rid):
    loan = get_loan_or_404(lid)
    req = store.pmi_requests.get(rid)
    if req is None or req["loan_id"] != lid:
        raise err_resource_not_found("PmiRemovalRequest not found under loan.")
    if req["decision"] != "PENDING":
        raise err_invalid_state("Only PENDING requests can be denied.")
    body = get_json()
    reason = body.get("denial_reason")
    if reason not in _ALLOWED_DENIAL_REASONS:
        raise err_invalid_state("Invalid denial_reason.")
    now = store.now()
    req["decision"] = "DENIED"
    req["denial_reason"] = reason
    bump(req, now)
    loan["pmi_status"] = "ACTIVE"
    bump(loan, now)
    return success(pmi_request_view(req), 200)
