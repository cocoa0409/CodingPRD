"""Loan & LoanRepayment service: request, approve, reject, repayment posting."""

import db
from config import (
    PLAN_ACTIVE,
    PARTICIPANT_ACTIVE, PARTICIPANT_SUSPENDED,
    LOAN_REQUESTED, LOAN_ACTIVE, LOAN_SATISFIED, LOAN_REJECTED, LOAN_DEFAULTED,
    REPAYMENT_POSTED,
    LOAN_NEXT_DUE_DAYS,
)
from errors import (
    AppError,
    ERR_INVALID_REQUEST,
    ERR_PLAN_NOT_ACTIVE,
    ERR_PARTICIPANT_NOT_IN_VALID_STATE,
    ERR_LOAN_TERM_INVALID,
    ERR_LOAN_NOT_REQUESTED,
    ERR_LOAN_ALREADY_OUTSTANDING,
    ERR_LOAN_EXCEEDS_MAX,
    ERR_LOAN_OVERPAYMENT,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from utils import stamp_create, stamp_ledger_create, bump_version, add_days
from services.occ import check_version
from services.calculations import (
    vested_percent, max_loan_amount_cents, monthly_payment_cents,
    highest_outstanding_in_window,
)
from services.vesting import get_current_date_for_plan
from services import sod


def _ensure_plan_active(plan: dict) -> None:
    if plan["status"] != PLAN_ACTIVE:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE.", 409)


def _loans_for_participant(plan_id: str, participant_id: str) -> list:
    return [l for l in db.loans.values()
            if l.get("plan_id") == plan_id and l.get("participant_id") == participant_id]


def _repayments_by_loan(plan_id: str, participant_id: str) -> dict:
    out: dict = {}
    for r in db.loan_repayments.values():
        if r.get("plan_id") == plan_id and r.get("participant_id") == participant_id:
            out.setdefault(r["loan_id"], []).append(r)
    return out


def _check_max_loan(plan: dict, participant: dict, requested_cents: int) -> None:
    current_date = get_current_date_for_plan(plan)
    if current_date is None:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan clock not initialized.", 409)
    pct = vested_percent(plan, participant, current_date)
    loans = _loans_for_participant(plan["id"], participant["id"])
    reps = _repayments_by_loan(plan["id"], participant["id"])
    hi = highest_outstanding_in_window(loans, reps, current_date)
    max_amt = max_loan_amount_cents(int(participant.get("total_account_balance_cents", 0)),
                                    pct, hi)
    if requested_cents > max_amt:
        raise AppError(ERR_LOAN_EXCEEDS_MAX,
                       "Requested amount exceeds maximum loan amount.", 422)


def request_loan(plan: dict, participant: dict, payload: dict,
                 actor_user_id: str) -> dict:
    _ensure_plan_active(plan)
    if participant["status"] not in (PARTICIPANT_ACTIVE, PARTICIPANT_SUSPENDED):
        raise AppError(ERR_PARTICIPANT_NOT_IN_VALID_STATE,
                       "Participant must be ACTIVE or SUSPENDED to request a loan.", 409)

    if not isinstance(payload, dict):
        raise AppError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    requested = payload.get("requested_amount_cents")
    term = payload.get("term_months")
    if not isinstance(requested, int) or isinstance(requested, bool) or requested <= 0:
        raise AppError(ERR_INVALID_REQUEST,
                       "requested_amount_cents must be a positive integer.", 400)
    if not isinstance(term, int) or isinstance(term, bool):
        raise AppError(ERR_LOAN_TERM_INVALID, "term_months must be an integer in [1..60].", 400)
    if term < 1 or term > 60:
        raise AppError(ERR_LOAN_TERM_INVALID, "term_months must be in [1..60].", 400)

    # Priority 9: one outstanding loan per participant
    for l in _loans_for_participant(plan["id"], participant["id"]):
        if l.get("status") in (LOAN_REQUESTED, LOAN_ACTIVE):
            raise AppError(ERR_LOAN_ALREADY_OUTSTANDING,
                           "Participant already has an outstanding loan.", 409)

    # Priority 10: max loan amount
    _check_max_loan(plan, participant, requested)

    loan = {
        "plan_id": plan["id"],
        "participant_id": participant["id"],
        "requested_amount_cents": int(requested),
        "approved_amount_cents": None,
        "term_months": int(term),
        "monthly_payment_cents": None,
        "outstanding_principal_cents": int(requested),  # provisional, not yet debited
        "payments_made": 0,
        "origination_date": None,
        "next_due_date": None,
        "status": LOAN_REQUESTED,
    }
    stamp_create(loan)
    db.loans[loan["id"]] = loan

    # Audit for SoD
    sod.record_loan_request(actor_user_id, plan["id"], loan["id"], participant["id"])
    return loan


def approve_loan(plan: dict, participant: dict, loan: dict, body: dict | None,
                 actor_user_id: str) -> dict:
    _ensure_plan_active(plan)
    if participant["status"] not in (PARTICIPANT_ACTIVE, PARTICIPANT_SUSPENDED):
        raise AppError(ERR_PARTICIPANT_NOT_IN_VALID_STATE,
                       "Participant must be ACTIVE or SUSPENDED for loan approval.", 409)
    if loan["status"] != LOAN_REQUESTED:
        raise AppError(ERR_LOAN_NOT_REQUESTED, "Loan is not in REQUESTED status.", 409)

    # Segregation of duties: same user may not have requested THIS loan
    if sod.has_user_requested_loan(actor_user_id, plan["id"], loan["id"]):
        raise AppError(ERR_INSUFFICIENT_PERMISSIONS,
                       "Segregation-of-duties: requester may not approve their own loan.", 403)
    # SoD: same user may not have posted any ContributionRecord under this plan in current plan_year
    if sod.has_user_posted_contribution(actor_user_id, plan["id"], plan.get("plan_year", 0)):
        raise AppError(ERR_INSUFFICIENT_PERMISSIONS,
                       "Segregation-of-duties: payroll poster may not approve a loan in the same plan year.", 403)

    # Re-check: one outstanding loan per participant — a sibling reached ACTIVE first?
    for l in _loans_for_participant(plan["id"], participant["id"]):
        if l["id"] == loan["id"]:
            continue
        if l.get("status") == LOAN_ACTIVE:
            raise AppError(ERR_LOAN_ALREADY_OUTSTANDING,
                           "Another loan is already active for this participant.", 409)

    # Re-check max loan amount
    _check_max_loan(plan, participant, int(loan["requested_amount_cents"]))

    check_version(body or {}, loan)

    current_date = get_current_date_for_plan(plan)
    if current_date is None:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan clock not initialized.", 409)

    loan["approved_amount_cents"] = int(loan["requested_amount_cents"])
    loan["origination_date"] = current_date
    loan["next_due_date"] = add_days(current_date, LOAN_NEXT_DUE_DAYS)
    loan["monthly_payment_cents"] = monthly_payment_cents(loan["approved_amount_cents"],
                                                          loan["term_months"])
    loan["outstanding_principal_cents"] = int(loan["approved_amount_cents"])
    loan["status"] = LOAN_ACTIVE
    bump_version(loan)
    return loan


def reject_loan(plan: dict, participant: dict, loan: dict, body: dict | None) -> dict:
    _ensure_plan_active(plan)
    if loan["status"] != LOAN_REQUESTED:
        raise AppError(ERR_LOAN_NOT_REQUESTED, "Loan is not in REQUESTED status.", 409)
    check_version(body or {}, loan)
    loan["status"] = LOAN_REJECTED
    bump_version(loan)
    return loan


def post_repayment(plan: dict, participant: dict, loan: dict, payload: dict) -> dict:
    _ensure_plan_active(plan)
    # PRD §3.5: repayment requires the loan to be ACTIVE. The closest catalog code is
    # the resource-state error class — there is no ERR_LOAN_NOT_ACTIVE, so we treat
    # a non-ACTIVE loan as a generic participant-resource-state mismatch.
    if loan["status"] != LOAN_ACTIVE:
        raise AppError(ERR_PARTICIPANT_NOT_IN_VALID_STATE,
                       "Loan must be ACTIVE to accept repayments.", 409)
    if not isinstance(payload, dict):
        raise AppError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    amount = payload.get("payment_amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise AppError(ERR_INVALID_REQUEST, "payment_amount_cents must be a positive integer.", 400)

    outstanding = int(loan.get("outstanding_principal_cents", 0))
    if amount > outstanding:
        raise AppError(ERR_LOAN_OVERPAYMENT,
                       "Repayment exceeds outstanding principal.", 422)

    current_date = get_current_date_for_plan(plan)
    if current_date is None:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan clock not initialized.", 409)

    repayment = {
        "plan_id": plan["id"],
        "participant_id": participant["id"],
        "loan_id": loan["id"],
        "payment_amount_cents": int(amount),
        "principal_cents": int(amount),
        "posted_on": current_date,
        "status": REPAYMENT_POSTED,
    }
    stamp_ledger_create(repayment)
    db.loan_repayments[repayment["id"]] = repayment

    # Side effects on Loan
    loan["outstanding_principal_cents"] = outstanding - int(amount)
    loan["payments_made"] = int(loan.get("payments_made", 0)) + 1
    loan["next_due_date"] = add_days(loan.get("next_due_date", current_date), LOAN_NEXT_DUE_DAYS)
    if loan["outstanding_principal_cents"] == 0:
        loan["status"] = LOAN_SATISFIED
    bump_version(loan)
    return repayment


def list_loans(plan: dict, participant: dict, limit: int, offset: int,
               status_filter: str | None):
    items = _loans_for_participant(plan["id"], participant["id"])
    if status_filter:
        items = [l for l in items if l.get("status") == status_filter]
    items.sort(key=lambda l: l.get("created_at", ""))
    total = len(items)
    return items[offset:offset + limit], total
