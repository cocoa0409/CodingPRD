"""Redeposits: record, credit, reject (PRD §3.9; 60-day window §3.7)."""

from flask import Blueprint

import errors
from db import create_entity, store, touch
from middleware import body, req_int, require_roles
from response import ok
from services import (
    case_owner_participant_id,
    complete_indirect_case,
    credited_total,
    find_or_create_source_row,
    parse_date,
    req_date,
    serialize_redeposit,
    update_5498,
)

bp = Blueprint("redeposits", __name__)


def _deadline_for(redeposit):
    if redeposit.get("rollover_case_id"):
        case = store.cases.get(redeposit["rollover_case_id"])
        return case.get("rollover_deadline_date") if case else None
    if redeposit.get("loan_id"):
        loan = store.loans.get(redeposit["loan_id"])
        return loan.get("offset_rollover_deadline") if loan else None
    return None


def _check_deadline(redeposit):
    deadline = _deadline_for(redeposit)
    received = parse_date(redeposit["received_date"])
    dl = parse_date(deadline) if deadline else None
    # Inclusive upper bound: deposit ON the deadline date is timely (PRD §3.7).
    if dl is None or received is None or received > dl:
        raise errors.err_deposit_past_deadline()


@bp.post("/v1/redeposits")
@require_roles("RolloverProcessor")
def create_redeposit():
    data = body()
    receiving_account_id = data.get("receiving_account_id")
    if not isinstance(receiving_account_id, str) or not receiving_account_id:
        raise errors.err_validation("receiving_account_id is required")
    case_id = data.get("rollover_case_id")
    loan_id = data.get("loan_id")
    if (case_id is None) == (loan_id is None):
        raise errors.err_validation("exactly one of rollover_case_id / loan_id must be set")
    received_date = req_date(data, "received_date")
    amount = req_int(data, "amount_cents")

    # Existence, left-to-right (priority 3).
    recv = store.accounts.get(receiving_account_id)
    if recv is None:
        raise errors.err_account_not_found()
    case = loan = None
    if case_id is not None:
        case = store.cases.get(case_id)
        if case is None:
            raise errors.err_case_not_found()
        if not case.get("rollover_deadline_date"):
            raise errors.err_case_invalid_state("Case has no disbursement issued")
    else:
        loan = store.loans.get(loan_id)
        if loan is None:
            raise errors.err_loan_not_found()
        if loan["status"] != "OFFSET" or not loan.get("offset_rollover_deadline"):
            raise errors.err_loan_invalid_state("Loan is not OFFSET")

    # Cross-reference (priority 6): same participant as the linked case/loan.
    if case is not None:
        owner = case_owner_participant_id(case)
    else:
        acct = store.accounts.get(loan["account_id"])
        owner = acct["participant_id"] if acct else None
    if recv["participant_id"] != owner:
        raise errors.err_participant_mismatch()

    # Temporal gate at creation (priority 7); re-checked at credit time.
    tmp = {"rollover_case_id": case_id, "loan_id": loan_id, "received_date": received_date.isoformat()}
    _check_deadline(tmp)

    # Amount checks last (priority 9).
    if amount <= 0:
        raise errors.err_validation("amount_cents must be > 0")
    if case is not None:
        remaining = (case.get("gross_cents") or 0) - credited_total(case["id"])
    else:
        remaining = loan["outstanding_balance_cents"] - loan.get("offset_repaid_cents", 0)
    if amount > remaining:
        raise errors.err_deposit_exceeds_remaining()

    red = create_entity(
        store.redeposits,
        {
            "rollover_case_id": case_id,
            "loan_id": loan_id,
            "receiving_account_id": receiving_account_id,
            "amount_cents": amount,
            "received_date": received_date.isoformat(),
            "status": "PENDING_VERIFICATION",
        },
    )
    return ok(serialize_redeposit(red), status=201)


@bp.post("/v1/redeposits/<red_id>/credit")
@require_roles("RolloverProcessor")
def credit_redeposit(red_id):
    red = store.redeposits.get(red_id)
    if red is None:
        raise errors.err_redeposit_not_found()
    if red["status"] != "PENDING_VERIFICATION":
        raise errors.err_redeposit_invalid_state()
    recv = store.accounts.get(red["receiving_account_id"])
    if recv is None or recv["status"] != "ACTIVE":
        raise errors.err_account_not_active()
    _check_deadline(red)  # deadline gate re-checked at credit time

    red["status"] = "CREDITED"
    touch(red)

    if red.get("rollover_case_id"):
        case = store.cases.get(red["rollover_case_id"])
        # Default credit into PRE_TAX with basis unchanged (PRD §3.9).
        row = find_or_create_source_row(recv["id"], "PRE_TAX")
        row["balance_cents"] += red["amount_cents"]
        touch(row)
        touch(recv)
        # DRAFT 5498 for the receiving participant and the credit (received) tax year.
        tax_year = parse_date(red["received_date"]).year
        update_5498(recv["participant_id"], recv["id"], tax_year, red["amount_cents"])
        if case is not None:
            touch(case)  # derived credited_total_cents changed (PRD §2.5)
            if case["status"] == "AWAITING_REDEPOSIT" and credited_total(case["id"]) >= (case.get("gross_cents") or 0):
                complete_indirect_case(case)  # equality completes (boundary)
    else:
        loan = store.loans.get(red["loan_id"])
        if loan is not None:
            loan["offset_repaid_cents"] = loan.get("offset_repaid_cents", 0) + red["amount_cents"]
            touch(loan)
    return ok(serialize_redeposit(red))


@bp.post("/v1/redeposits/<red_id>/reject")
@require_roles("RolloverProcessor")
def reject_redeposit(red_id):
    red = store.redeposits.get(red_id)
    if red is None:
        raise errors.err_redeposit_not_found()
    if red["status"] != "PENDING_VERIFICATION":
        raise errors.err_redeposit_invalid_state()
    red["status"] = "REJECTED"
    touch(red)
    return ok(serialize_redeposit(red))
