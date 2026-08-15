from datetime import timedelta
from flask import Blueprint

from db import store, base_fields, touch
from dates import req_date, parse_date
from errors import (err, ERR_ACCOUNT_NOT_FOUND, ERR_RESOURCE_NOT_FOUND,
                    ERR_ACCOUNT_STATE_INVALID, ERR_PLAN_ALREADY_ACTIVE,
                    ERR_NO_BALANCE_DUE, ERR_STALE_VERSION,
                    ERR_PLAN_STATE_INVALID, ERR_INSTALLMENT_STATE_INVALID,
                    ERR_INSTALLMENT_AMOUNT_MISMATCH, ERR_INVALID_REQUEST)
from middleware import auth_context, require_roles, forbid
from response import success, json_body, req_str, req_int, list_response
from serialize import ser_plan, ser_installment
from services.core import post_entry, recompute_account
from services.domain import split_installments, plan_installments, cancel_plan

bp = Blueprint("plans", __name__)


def _load_plan(pid, uid, role):
    p = store.plans.get(pid)
    if p is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Payment plan not found")
    if role == "Student":
        a = store.accounts.get(p["account_id"])
        if a is None or a["student_id"] != uid:
            forbid()
    return p


@bp.post("/bursar/payment-plans")
def create_plan():
    uid, role = auth_context()
    require_roles(role, "Student", "BursarStaff", "BursarManager")
    body = json_body()
    account_id = req_str(body, "account_id")
    count = req_int(body, "installment_count")
    first_due = req_date(body, "first_due_date")
    expected = req_int(body, "expected_account_version")

    account = store.accounts.get(account_id)
    if account is None:
        raise err(ERR_ACCOUNT_NOT_FOUND, "Account not found")
    if role == "Student" and account["student_id"] != uid:
        forbid()
    if not (2 <= count <= 6):
        raise err(ERR_INVALID_REQUEST, "installment_count must be between 2 and 6")
    if account["status"] not in ("OPEN", "PAST_DUE"):
        raise err(ERR_ACCOUNT_STATE_INVALID,
                  "Plan creation requires the account to be OPEN or PAST_DUE")
    # At most one live plan per account: an ACTIVE plan blocks creation; a
    # DEFAULTED plan is instead superseded.
    defaulted_existing = None
    for p in store.plans.values():
        if p["account_id"] == account["id"]:
            if p["status"] == "ACTIVE":
                raise err(ERR_PLAN_ALREADY_ACTIVE,
                          "An ACTIVE plan already exists on this account")
            if p["status"] == "DEFAULTED":
                defaulted_existing = p
    if account["balance_cents"] <= 0:
        raise err(ERR_NO_BALANCE_DUE, "Plan creation requires a positive balance")
    # OCC runs last, after all business rules pass.
    if expected != account["version"]:
        raise err(ERR_STALE_VERSION, "expected_account_version does not match the account version")

    # Supersession: the DEFAULTED plan is cancelled (non-PAID installments
    # cancelled, acceleration lifted) before the new principal is captured.
    if defaulted_existing is not None:
        cancel_plan(defaulted_existing)

    term = store.terms[account["term_id"]]
    principal = account["balance_cents"]
    fee = term["plan_setup_fee_cents"]
    total = principal + fee

    plan = base_fields()
    plan.update({
        "account_id": account["id"], "installment_count": count,
        "first_due_date": first_due.isoformat(), "principal_cents": principal,
        "fee_cents": fee, "total_cents": total, "defaulted_count": 0,
        "status": "ACTIVE",
    })
    store.plans[plan["id"]] = plan

    amounts = split_installments(total, count)
    for k in range(1, count + 1):
        i = base_fields()
        i.update({
            "plan_id": plan["id"], "sequence": k,
            "due_date": (first_due + timedelta(days=30 * (k - 1))).isoformat(),
            "amount_cents": amounts[k - 1], "paid_cents": 0,
            "late_fee_posted": False, "status": "SCHEDULED",
        })
        store.installments[i["id"]] = i

    post_entry(account["id"], "PLAN_FEE", fee, due_date=first_due.isoformat(),
               source_ref=plan["id"], memo="Payment plan setup fee")
    recompute_account(account, force_bump=True)
    return success(ser_plan(plan), status=201)


@bp.get("/bursar/payment-plans/<pid>")
def get_plan(pid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    p = _load_plan(pid, uid, role)
    return success(ser_plan(p))


@bp.get("/bursar/accounts/<aid>/payment-plans")
def list_plans(aid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    a = store.accounts.get(aid)
    if a is None:
        raise err(ERR_ACCOUNT_NOT_FOUND, "Account not found")
    if role == "Student" and a["student_id"] != uid:
        forbid()
    rows = [p for p in store.plans.values() if p["account_id"] == aid]
    rows.sort(key=lambda p: p["_seq"])
    return list_response(rows, ser_plan)


@bp.post("/bursar/payment-plans/<pid>/cancel")
def cancel_plan_endpoint(pid):
    uid, role = auth_context()
    require_roles(role, "Student", "BursarStaff", "BursarManager")
    p = _load_plan(pid, uid, role)
    if p["status"] not in ("ACTIVE", "DEFAULTED"):
        raise err(ERR_PLAN_STATE_INVALID,
                  "Only an ACTIVE or DEFAULTED plan can be cancelled")
    cancel_plan(p)
    account = store.accounts[p["account_id"]]
    recompute_account(account, force_bump=True)
    return success(ser_plan(p))


@bp.get("/bursar/payment-plans/<pid>/installments")
def list_installments(pid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    p = _load_plan(pid, uid, role)
    return list_response(plan_installments(p["id"]), ser_installment)


@bp.post("/bursar/installments/<iid>/pay")
def pay_installment(iid):
    uid, role = auth_context()
    require_roles(role, "Student", "BursarStaff", "BursarManager")
    inst = store.installments.get(iid)
    if inst is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Installment not found")
    plan = store.plans[inst["plan_id"]]
    account = store.accounts[plan["account_id"]]
    if role == "Student" and account["student_id"] != uid:
        forbid()
    body = json_body()
    amount = req_int(body, "amount_cents")
    if inst["status"] not in ("SCHEDULED", "PAST_DUE"):
        raise err(ERR_INSTALLMENT_STATE_INVALID,
                  "Installment is not payable in its current state")
    if plan["status"] not in ("ACTIVE", "DEFAULTED"):
        raise err(ERR_PLAN_STATE_INVALID, "The parent plan is not active")
    if amount != inst["amount_cents"] - inst["paid_cents"]:
        raise err(ERR_INSTALLMENT_AMOUNT_MISMATCH,
                  "amount_cents must equal the remaining installment amount")

    inst["paid_cents"] = inst["amount_cents"]
    inst["status"] = "PAID"
    touch(inst)
    post_entry(account["id"], "PAYMENT", amount, source_ref=inst["id"],
               memo="Installment payment")

    # Plan cure / completion evaluation.
    siblings = plan_installments(plan["id"])
    if all(i["status"] == "PAID" for i in siblings):
        plan["status"] = "COMPLETED"
        touch(plan)
    elif plan["status"] == "DEFAULTED" and \
            not any(i["status"] == "PAST_DUE" for i in siblings):
        plan["status"] = "ACTIVE"  # cure: acceleration lifted
        touch(plan)
    recompute_account(account, force_bump=True)
    return success(ser_installment(inst))
