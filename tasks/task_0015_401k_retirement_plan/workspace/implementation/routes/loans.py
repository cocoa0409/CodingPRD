"""Loan resource — create, get, list, disburse, repay, default."""

from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOAN_ALREADY_OUTSTANDING,
    ERR_LOAN_EXCEEDS_LIMIT,
    ERR_NOT_FOUND,
)
from middleware import auth_required
from response import success_array, success_object
from services.calculations import loan_monthly_payment
from services.entities import (
    recompute_outstanding_loan_principal,
    recompute_vested_balance,
    serialize_loan,
    stamp_create,
    stamp_update,
)
from services.validators import require_dict, require_int, require_str


bp = Blueprint("loans", __name__)


LOAN_STATUSES = {"REQUESTED", "DISBURSED", "REPAID", "DEFAULTED"}
LOAN_HARD_CAP_CENTS = 5_000_000
MAX_GENERAL_TERM_MONTHS = 60
# Primary-residence loans may go up to 180 months. We don't have a category flag
# on the Loan, so we accept any term in [1, 180] at creation per §1.4 priority
# 15 (ERR_INVALID_REQUEST shape check). The scaffold validation says
# "1 <= term_months <= 60 for general; <= 180 for primary-residence" — since
# the field set doesn't include a category discriminator we honor the broader
# upper bound (180) which keeps both classes representable.
MAX_LOAN_TERM_MONTHS = 180


def _get_loan_or_404(lid: str) -> dict:
    l = db.loans.get(lid)
    if not l:
        raise APIError(ERR_NOT_FOUND, 404, f"Loan '{lid}' not found")
    return l


@bp.post("/loans")
@auth_required("PlanAdmin", "Participant")
def create_loan():
    body = require_dict(request.get_json(silent=True))
    participant_id = require_str(body, "participant_id")
    principal = require_int(body, "principal_cents", strictly_positive=True)
    term = require_int(body, "term_months", minimum=1, maximum=MAX_LOAN_TERM_MONTHS)
    rate = require_int(body, "annual_interest_rate_bps", minimum=1, maximum=2500)

    with db.LOCK:
        if participant_id not in db.participants:
            raise APIError(ERR_NOT_FOUND, 404, f"Participant '{participant_id}' not found")
        if g.user_role == "Participant" and g.user_id != participant_id:
            raise APIError(ERR_FORBIDDEN, 403, "Participant may only create own loans")
        l = stamp_create(
            {
                "participant_id": participant_id,
                "principal_cents": principal,
                "term_months": term,
                "annual_interest_rate_bps": rate,
                "monthly_payment_cents": 0,
                "outstanding_principal_cents": 0,
                "status": "REQUESTED",
            }
        )
        db.loans[l["id"]] = l
    return success_object(serialize_loan(l), status=201)


@bp.get("/loans/<lid>")
@auth_required("PlanAdmin", "Custodian", "Participant")
def get_loan(lid: str):
    l = _get_loan_or_404(lid)
    if g.user_role == "Participant" and g.user_id != l["participant_id"]:
        raise APIError(ERR_FORBIDDEN, 403, "Participant may only read own loans")
    return success_object(serialize_loan(l))


@bp.get("/loans")
@auth_required("PlanAdmin", "Custodian", "Participant")
def list_loans():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset out of range")
    participant_filter = request.args.get("participant_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in LOAN_STATUSES:
        raise APIError(ERR_INVALID_REQUEST, 400, "invalid status filter")

    with db.LOCK:
        items = list(db.loans.values())
    if participant_filter is not None:
        items = [l for l in items if l["participant_id"] == participant_filter]
    if status_filter is not None:
        items = [l for l in items if l["status"] == status_filter]
    if g.user_role == "Participant":
        items = [l for l in items if l["participant_id"] == g.user_id]
    items.sort(key=lambda l: l["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_array(
        [serialize_loan(l) for l in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )


# -----------------------------------------------------------------------------
# Disburse
# -----------------------------------------------------------------------------


@bp.post("/loans/<lid>/disburse")
@auth_required("PlanAdmin")
def disburse_loan(lid: str):
    with db.LOCK:
        loan = _get_loan_or_404(lid)
        if loan["status"] != "REQUESTED":
            raise APIError(ERR_INVALID_STATE, 409, "Loan is not REQUESTED")
        participant = db.participants.get(loan["participant_id"])
        if not participant:
            raise APIError(ERR_NOT_FOUND, 404, "Participant not found")
        plan = db.plans.get(participant["plan_id"])
        if not plan:
            raise APIError(ERR_NOT_FOUND, 404, "Plan not found")
        if plan["status"] != "ACTIVE":
            raise APIError(ERR_INVALID_STATE, 409, "Plan must be ACTIVE to disburse")
        if participant["enrollment_status"] != "ENROLLED":
            raise APIError(ERR_INVALID_STATE, 409, "Participant must be ENROLLED to disburse")

        # One-loan-at-a-time rule.
        for other in db.loans.values():
            if other["id"] == loan["id"]:
                continue
            if other["participant_id"] == loan["participant_id"] and other["status"] == "DISBURSED":
                raise APIError(
                    ERR_LOAN_ALREADY_OUTSTANDING,
                    409,
                    "Participant already has a DISBURSED loan",
                )

        # Borrowing limit:
        # principal <= floor(min((employee_balance + vested_employer_balance) * 0.5, 5_000_000))
        vested_total = participant["employee_balance_cents"] + participant["vested_employer_balance_cents"]
        cap_a = vested_total // 2  # floor(... * 0.5) -> integer division by 2
        cap_b = LOAN_HARD_CAP_CENTS
        limit = min(cap_a, cap_b)
        if loan["principal_cents"] > limit:
            raise APIError(
                ERR_LOAN_EXCEEDS_LIMIT,
                422,
                f"principal {loan['principal_cents']} exceeds borrowing limit {limit}",
            )

        # Compute amortization.
        loan["monthly_payment_cents"] = loan_monthly_payment(
            principal_cents=loan["principal_cents"],
            term_months=loan["term_months"],
            annual_interest_rate_bps=loan["annual_interest_rate_bps"],
        )
        loan["outstanding_principal_cents"] = loan["principal_cents"]
        loan["status"] = "DISBURSED"
        stamp_update(loan)

        # Depth 2 reconciliation on participant.
        recompute_outstanding_loan_principal(participant)
        stamp_update(participant)
    return success_object(serialize_loan(loan))


# -----------------------------------------------------------------------------
# Repay
# -----------------------------------------------------------------------------


@bp.post("/loans/<lid>/repay")
@auth_required("PlanAdmin", "Participant")
def repay_loan(lid: str):
    body = require_dict(request.get_json(silent=True))
    amount = require_int(body, "amount_cents", strictly_positive=True)
    with db.LOCK:
        loan = _get_loan_or_404(lid)
        if g.user_role == "Participant" and g.user_id != loan["participant_id"]:
            raise APIError(ERR_FORBIDDEN, 403, "Participant may only repay own loans")
        if loan["status"] != "DISBURSED":
            raise APIError(ERR_INVALID_STATE, 409, "Loan is not DISBURSED")
        if amount < loan["outstanding_principal_cents"]:
            raise APIError(
                ERR_INVALID_STATE,
                409,
                "amount_cents must be >= outstanding_principal_cents for full repayment",
            )

        prior_outstanding = loan["outstanding_principal_cents"]
        loan["outstanding_principal_cents"] = 0
        loan["status"] = "REPAID"
        stamp_update(loan)

        participant = db.participants.get(loan["participant_id"])
        if participant:
            recompute_outstanding_loan_principal(participant)
            stamp_update(participant)
    return success_object(serialize_loan(loan))


# -----------------------------------------------------------------------------
# Default (operator-initiated)
# -----------------------------------------------------------------------------


@bp.post("/loans/<lid>/default")
@auth_required("PlanAdmin")
def default_loan(lid: str):
    with db.LOCK:
        loan = _get_loan_or_404(lid)
        if loan["status"] != "DISBURSED":
            raise APIError(ERR_INVALID_STATE, 409, "Loan is not DISBURSED")
        prior_outstanding = loan["outstanding_principal_cents"]
        loan["status"] = "DEFAULTED"
        stamp_update(loan)

        participant = db.participants.get(loan["participant_id"])
        if participant:
            # Deemed distribution: deduct unpaid principal from employer_balance_cents.
            participant["employer_balance_cents"] -= prior_outstanding
            recompute_outstanding_loan_principal(participant)
            recompute_vested_balance(participant)
            stamp_update(participant)
    return success_object(serialize_loan(loan))
