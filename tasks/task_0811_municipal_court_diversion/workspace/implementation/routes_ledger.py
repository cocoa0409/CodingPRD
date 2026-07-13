"""Routes: ledger accounts, installment plans, payments, reversals."""

from decimal import Decimal
from flask import Blueprint, request, g

from errors import ApiError
from auth import endpoint, ALL_ROLES
from store import db, now, base_fields, touch, serialize
from envelope import success, parse_pagination, list_response
import bodyutil as B
import calc
from domain import (account_of_case, payments_of_account, plans_of_account,
                    diversion_of_case, recompute_account, recompute_agreement,
                    bucket_outstanding, try_settle_account)
from routes_core import get_case

bp_ledger = Blueprint("ledger", __name__)

from datetime import timedelta


def get_account(aid):
    a = db.ledger_accounts.get(aid)
    if a is None:
        raise ApiError("ERR_LEDGER_ACCOUNT_NOT_FOUND", "ledger account not found")
    return a


def get_payment(pid):
    p = db.payments.get(pid)
    if p is None:
        raise ApiError("ERR_PAYMENT_NOT_FOUND", "payment not found")
    return p


def _recompute_case_agreement(account):
    agr = diversion_of_case(account["case_id"])
    if agr is not None:
        recompute_agreement(agr)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@bp_ledger.get("/cases/<cid>/ledger-account")
@endpoint(ALL_ROLES)
def fetch_case_ledger(cid):
    get_case(cid)
    acct = account_of_case(cid)
    data = [serialize(acct)] if acct is not None else []
    return success(data, response_type="array", status=200)


@bp_ledger.get("/ledger-accounts/<aid>")
@endpoint(ALL_ROLES)
def fetch_account(aid):
    return success(serialize(get_account(aid)))


# ---------------------------------------------------------------------------
# installment plans
# ---------------------------------------------------------------------------
@bp_ledger.post("/ledger-accounts/<aid>/installment-plans")
@endpoint(["Cashier"])
def create_plan(aid):
    acct = get_account(aid)
    # state
    if acct["status"] == "CLOSED":
        raise ApiError("ERR_ACCOUNT_CLOSED", "account is closed")
    body = B.get_body()
    # concurrency (OCC) — checked before business constraints
    if "expected_ledger_account_version" in body and body["expected_ledger_account_version"] is not None:
        exp = body["expected_ledger_account_version"]
        if not isinstance(exp, int) or isinstance(exp, bool):
            raise ApiError("ERR_VALIDATION", "expected_ledger_account_version must be an integer")
        if exp != acct["version"]:
            raise ApiError("ERR_STALE_VERSION", "stale ledger account version")
    # installment count range
    if "num_installments" in body and body["num_installments"] is not None:
        n = body["num_installments"]
        if not isinstance(n, int) or isinstance(n, bool):
            raise ApiError("ERR_VALIDATION", "num_installments must be an integer")
        if n < calc.INSTALLMENT_COUNT_MIN or n > calc.INSTALLMENT_COUNT_MAX:
            raise ApiError("ERR_INVALID_INSTALLMENT_COUNT", "num_installments out of range")
    # minimum balance
    if calc.to_decimal(acct["balance"]) < calc.INSTALLMENT_MIN_BALANCE:
        raise ApiError("ERR_INSTALLMENT_MINIMUM_NOT_MET", "balance below installment minimum")
    # body validation (required fields)
    num_installments = B.req_int(body, "num_installments", minimum=None)
    if "expected_ledger_account_version" not in body or body["expected_ledger_account_version"] is None:
        raise ApiError("ERR_VALIDATION", "'expected_ledger_account_version' is required")

    inst_amt, final_amt = calc.installment_schedule(acct["balance"], num_installments)
    # supersede a prior ACTIVE plan
    for prior in plans_of_account(aid):
        if prior["status"] == "ACTIVE":
            prior["status"] = "SUPERSEDED"
            touch(prior)
    plan = base_fields()
    plan.update({
        "ledger_account_id": aid,
        "num_installments": num_installments,
        "installment_amount": inst_amt,
        "final_installment_amount": final_amt,
        "next_due_date": now() + timedelta(days=calc.INSTALLMENT_INTERVAL_DAYS),
        "status": "ACTIVE",
    })
    db.installment_plans[plan["id"]] = plan
    # creating a plan bumps the account version
    touch(acct, bump_version=True)
    return success(serialize(plan), status=201)


@bp_ledger.get("/ledger-accounts/<aid>/installment-plans")
@endpoint(ALL_ROLES)
def list_plans(aid):
    get_account(aid)
    limit, offset = parse_pagination(request.args)
    return list_response(plans_of_account(aid), limit, offset, serialize)


# ---------------------------------------------------------------------------
# payments
# ---------------------------------------------------------------------------
@bp_ledger.post("/ledger-accounts/<aid>/payments")
@endpoint(["Cashier", "Defendant"])
def record_payment(aid):
    acct = get_account(aid)
    # ownership: a Defendant may only pay their own case's account
    if g.user_role == "Defendant":
        case = db.cases[acct["case_id"]]
        if g.user_id != case["defendant_id"]:
            raise ApiError("ERR_UNAUTHORIZED", "defendant may pay only their own account")
    # state
    if acct["status"] == "CLOSED":
        raise ApiError("ERR_ACCOUNT_CLOSED", "account is closed")
    body = B.get_body()
    amount = B.req_decimal(body, "amount", exclusive_min=Decimal("0"))
    if amount > calc.to_decimal(acct["balance"]):
        raise ApiError("ERR_OVERPAYMENT", "payment exceeds outstanding balance")

    outstanding = bucket_outstanding(acct)
    remaining = amount
    alloc = {}
    for name in ("fines", "court_fee", "surcharge", "program_fee"):
        out = outstanding[name]
        if out < 0:
            out = Decimal("0")
        take = min(remaining, out)
        alloc[name] = calc.q2(take)
        remaining -= take

    pay = base_fields(with_common=False)
    pay.update({
        "ledger_account_id": aid,
        "amount": calc.q2(amount),
        "allocated_fines": alloc["fines"],
        "allocated_court_fee": alloc["court_fee"],
        "allocated_surcharge": alloc["surcharge"],
        "allocated_program_fee": alloc["program_fee"],
        "reversed": False,
    })
    db.payments[pay["id"]] = pay

    recompute_account(acct)
    touch(acct, bump_version=True)
    try_settle_account(acct)
    _recompute_case_agreement(acct)
    return success(serialize(pay), status=201)


@bp_ledger.get("/ledger-accounts/<aid>/payments")
@endpoint(ALL_ROLES)
def list_payments(aid):
    get_account(aid)
    limit, offset = parse_pagination(request.args)
    return list_response(payments_of_account(aid), limit, offset, serialize)


@bp_ledger.post("/payments/<pid>/reverse")
@endpoint(["Cashier"])
def reverse_payment(pid):
    pay = get_payment(pid)
    if pay["reversed"]:
        raise ApiError("ERR_PAYMENT_ALREADY_REVERSED", "payment already reversed")
    pay["reversed"] = True
    acct = db.ledger_accounts[pay["ledger_account_id"]]
    recompute_account(acct)
    if acct["status"] == "SETTLED" and calc.to_decimal(acct["balance"]) > 0:
        acct["status"] = "ASSESSED"
    touch(acct, bump_version=True)
    _recompute_case_agreement(acct)
    return success(serialize(pay), status=200)
