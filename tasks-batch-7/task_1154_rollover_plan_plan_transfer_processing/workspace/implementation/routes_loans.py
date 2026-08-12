"""Loans: create/list/get, transfer, offset (PRD §3.8)."""

from datetime import date

from flask import Blueprint, g, request

import errors
from db import clock_date, create_entity, now_iso, store, touch
from middleware import ALL_ROLES, body, paginate, req_int, require_roles
from response import ok, ok_list
from routes_accounts import get_account_or_404
from services import (
    AGE_THRESHOLD_MONTHS,
    WINDOW_DAYS,
    active_loans_of_account,  # noqa: F401  (kept for symmetry)
    add_days,
    age_months_on,
    draft_1099,
    parse_date,
    serialize_loan,
    serialize_redeposit,
)

bp = Blueprint("loans", __name__)


def get_loan_or_404(loan_id):
    loan = store.loans.get(loan_id)
    if loan is None:
        raise errors.err_loan_not_found()
    if g.role == "Participant":
        acct = store.accounts.get(loan["account_id"])
        if acct is None or acct["participant_id"] != g.user_id:
            raise errors.err_account_not_found()
    return loan


@bp.post("/v1/accounts/<account_id>/loans")
@require_roles("PlanSponsorAdmin")
def create_loan(account_id):
    get_account_or_404(account_id, ownership_mask=False)
    data = body()
    outstanding = req_int(data, "outstanding_balance_cents")
    if outstanding <= 0:
        raise errors.err_validation("outstanding_balance_cents must be > 0")
    rate = req_int(data, "interest_rate_bp")
    if rate < 0 or rate > 5000:
        raise errors.err_validation("interest_rate_bp must be in 0..5000")
    term = req_int(data, "term_months")
    if term < 1 or term > 360:
        raise errors.err_validation("term_months must be in 1..360")
    loan = create_entity(
        store.loans,
        {
            "account_id": account_id,
            "outstanding_balance_cents": outstanding,
            "interest_rate_bp": rate,
            "term_months": term,
            "status": "ACTIVE",
            "offset_at": None,
            "offset_qualified": None,
            "offset_rollover_deadline": None,
            "offset_repaid_cents": 0,
        },
    )
    return ok(serialize_loan(loan), status=201)


@bp.get("/v1/accounts/<account_id>/loans")
@require_roles(*ALL_ROLES)
def list_account_loans(account_id):
    get_account_or_404(account_id)
    rows = [l for l in store.loans.values() if l["account_id"] == account_id]
    status = request.args.get("status")
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    rows.sort(key=lambda l: l["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_loan(l) for l in page], total, limit, offset)


@bp.get("/v1/loans/<loan_id>")
@require_roles(*ALL_ROLES)
def get_loan(loan_id):
    return ok(serialize_loan(get_loan_or_404(loan_id)))


@bp.get("/v1/loans/<loan_id>/redeposits")
@require_roles(*ALL_ROLES)
def list_loan_redeposits(loan_id):
    get_loan_or_404(loan_id)
    rows = [r for r in store.redeposits.values() if r.get("loan_id") == loan_id]
    rows.sort(key=lambda r: r["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_redeposit(r) for r in page], total, limit, offset)


@bp.post("/v1/loans/<loan_id>/transfer")
@require_roles("RolloverProcessor")
def transfer_loan(loan_id):
    loan = store.loans.get(loan_id)
    if loan is None:
        raise errors.err_loan_not_found()
    data = body()
    receiving_account_id = data.get("receiving_account_id")
    if not isinstance(receiving_account_id, str) or not receiving_account_id:
        raise errors.err_validation("receiving_account_id is required")
    recv = store.accounts.get(receiving_account_id)
    if recv is None:
        raise errors.err_account_not_found()
    if loan["status"] != "ACTIVE":
        raise errors.err_loan_invalid_state()
    cur = store.accounts.get(loan["account_id"])
    if recv["status"] != "ACTIVE" or cur is None or recv["participant_id"] != cur["participant_id"]:
        raise errors.err_participant_mismatch()
    recv_plan = store.plans.get(recv["plan_id"])
    if (
        recv_plan is None
        or not recv_plan.get("accepts_loan_transfers", True)
        or recv_plan["status"] != "ACTIVE"
    ):
        raise errors.err_loan_not_transferrable()
    gate = any(
        c["case_type"] == "PLAN_TRANSFER"
        and c.get("source_account_id") == loan["account_id"]
        and c["status"] == "ACCEPTANCE_PENDING"
        and c.get("receiving_plan_id") == recv["plan_id"]
        for c in store.cases.values()
    )
    if not gate:
        raise errors.err_case_invalid_state(
            "No PLAN_TRANSFER case in ACCEPTANCE_PENDING on the source account naming the receiving plan"
        )
    loan["account_id"] = receiving_account_id
    loan["status"] = "TRANSFERRED"
    touch(loan)
    return ok(serialize_loan(loan))


@bp.post("/v1/loans/<loan_id>/offset")
@require_roles("RolloverProcessor")
def offset_loan(loan_id):
    loan = store.loans.get(loan_id)
    if loan is None:
        raise errors.err_loan_not_found()
    if loan["status"] != "ACTIVE":
        raise errors.err_loan_invalid_state()
    acct = store.accounts.get(loan["account_id"])
    participant = store.participants.get(acct["participant_id"]) if acct else None
    plan = store.plans.get(acct["plan_id"]) if acct else None
    today = clock_date()
    qualified = bool(
        (participant is not None and participant["employment_status"] in ("SEPARATED", "RETIRED"))
        or (plan is not None and plan["status"] == "TERMINATED")
    )
    if qualified:
        # October 15 of the year following the offset's tax year (filing deadline incl. extensions).
        deadline = date(today.year + 1, 10, 15)
    else:
        deadline = add_days(today, WINDOW_DAYS)
    loan["status"] = "OFFSET"
    loan["offset_at"] = now_iso()
    loan["offset_qualified"] = qualified
    loan["offset_rollover_deadline"] = deadline.isoformat()
    touch(loan)
    months = 0
    if participant is not None:
        dob = parse_date(participant["date_of_birth"])
        if dob is not None:
            months = age_months_on(dob, today)
    code = "CODE_7" if months >= AGE_THRESHOLD_MONTHS else "CODE_1"
    draft_1099(
        case_id=None,
        loan_id=loan["id"],
        participant_id=participant["id"] if participant else None,
        tax_year=today.year,
        gross=loan["outstanding_balance_cents"],
        withholding=0,
        taxable=loan["outstanding_balance_cents"],
        code=code,
    )
    return ok(serialize_loan(loan))
