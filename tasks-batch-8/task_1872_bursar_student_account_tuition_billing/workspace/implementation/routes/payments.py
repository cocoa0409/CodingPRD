from flask import Blueprint

from db import store, base_fields, touch
from errors import (err, ERR_ACCOUNT_NOT_FOUND, ERR_RESOURCE_NOT_FOUND,
                    ERR_ACCOUNT_STATE_INVALID, ERR_AMOUNT_INVALID,
                    ERR_PAYMENT_STATE_INVALID)
from middleware import auth_context, require_roles, forbid
from response import success, json_body, req_str, req_int, req_enum, list_response
from serialize import ser_payment
from services.core import (post_entry, open_amount, waterfall_targets,
                           recompute_account)

bp = Blueprint("payments", __name__)

METHODS = ("CARD", "ACH", "CASH", "CHECK")


def _load_payment(pid, uid, role):
    p = store.payments.get(pid)
    if p is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Payment not found")
    if role == "Student":
        a = store.accounts.get(p["account_id"])
        if a is None or a["student_id"] != uid:
            forbid()
    return p


@bp.post("/bursar/payments")
def create_payment():
    uid, role = auth_context()
    require_roles(role, "Student", "BursarStaff", "BursarManager")
    body = json_body()
    account_id = req_str(body, "account_id")
    amount = req_int(body, "amount_cents")
    method = req_enum(body, "method", METHODS)
    account = store.accounts.get(account_id)
    if account is None:
        raise err(ERR_ACCOUNT_NOT_FOUND, "Account not found")
    if role == "Student" and account["student_id"] != uid:
        forbid()
    if account["status"] not in ("OPEN", "PAST_DUE"):
        raise err(ERR_ACCOUNT_STATE_INVALID,
                  "Payments require the account to be OPEN or PAST_DUE")
    if amount <= 0:
        raise err(ERR_AMOUNT_INVALID, "amount_cents must be positive")

    # payment_waterfall: oldest obligation first (due_date ASC, created_at ASC).
    remaining = amount
    allocations = []
    for e in waterfall_targets(account["id"]):
        if remaining <= 0:
            break
        alloc = min(open_amount(e), remaining)
        if alloc > 0:
            allocations.append({"ledger_entry_id": e["id"], "amount_cents": alloc})
            remaining -= alloc

    p = base_fields()
    p.update({
        "account_id": account["id"], "amount_cents": amount, "method": method,
        "status": "POSTED", "allocations": allocations,
        "unapplied_cents": remaining, "reversed_reason": None,
    })
    store.payments[p["id"]] = p
    post_entry(account["id"], "PAYMENT", amount, source_ref=p["id"],
               memo="Payment received")
    recompute_account(account, force_bump=True)
    return success(ser_payment(p), status=201)


@bp.get("/bursar/payments/<pid>")
def get_payment(pid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    p = _load_payment(pid, uid, role)
    return success(ser_payment(p))


@bp.get("/bursar/accounts/<aid>/payments")
def list_payments(aid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    a = store.accounts.get(aid)
    if a is None:
        raise err(ERR_ACCOUNT_NOT_FOUND, "Account not found")
    if role == "Student" and a["student_id"] != uid:
        forbid()
    rows = [p for p in store.payments.values() if p["account_id"] == aid]
    rows.sort(key=lambda p: p["_seq"])
    return list_response(rows, ser_payment)


@bp.post("/bursar/payments/<pid>/reverse")
def reverse_payment(pid):
    uid, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    p = _load_payment(pid, uid, role)
    body = json_body()
    reason = req_str(body, "reason")
    if p["status"] != "POSTED":
        raise err(ERR_PAYMENT_STATE_INVALID, "Only a POSTED payment can be reversed")
    p["status"] = "REVERSED"
    p["reversed_reason"] = reason
    touch(p)
    account = store.accounts[p["account_id"]]
    # Allocations unwind automatically: open amounts count POSTED payments only.
    post_entry(account["id"], "PAYMENT_REVERSAL", p["amount_cents"],
               source_ref=p["id"], memo="Payment reversal")
    recompute_account(account, force_bump=True)
    return success(ser_payment(p))
