from flask import Blueprint, request

from db import store, touch
from errors import err, ERR_RESOURCE_NOT_FOUND, ERR_REFUND_STATE_INVALID
from middleware import auth_context, require_roles, forbid
from response import success, json_body, req_enum, list_response
from serialize import ser_refund
from services.core import (post_entry, recompute_account, account_entries,
                           compute_balance)
from services.domain import account_entries_for_enrollment

bp = Blueprint("refunds", __name__)


def _load_refund(rid, uid, role):
    r = store.refunds.get(rid)
    if r is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Refund not found")
    if role == "Student":
        a = store.accounts.get(r["account_id"])
        if a is None or a["student_id"] != uid:
            forbid()
    return r


@bp.get("/bursar/refunds/<rid>")
def get_refund(rid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    r = _load_refund(rid, uid, role)
    return success(ser_refund(r))


@bp.get("/bursar/refunds")
def list_refunds():
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    rows = list(store.refunds.values())
    if role == "Student":
        own_accounts = {a["id"] for a in store.accounts.values()
                        if a["student_id"] == uid}
        rows = [r for r in rows if r["account_id"] in own_accounts]
    for key in ("account_id", "enrollment_id", "status"):
        v = request.args.get(key)
        if v is not None:
            rows = [r for r in rows if r[key] == v]
    rows.sort(key=lambda r: r["_seq"])
    return list_response(rows, ser_refund)


@bp.post("/bursar/refunds/<rid>/transition")
def refund_transition(rid):
    uid, role = auth_context()
    require_roles(role, "BursarManager")
    r = store.refunds.get(rid)
    if r is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Refund not found")
    body = json_body()
    action = req_enum(body, "action", ("APPROVE", "VOID"))
    if r["status"] != "CALCULATED":
        raise err(ERR_REFUND_STATE_INVALID,
                  "Refund disposition requires CALCULATED status")

    if action == "VOID":
        # No ledger effect; the enrollment exit remains in force.
        r["status"] = "VOID"
        touch(r)
        return success(ser_refund(r))

    # APPROVE
    account = store.accounts[r["account_id"]]
    enrollment = store.enrollments[r["enrollment_id"]]
    # due_date copied from the enrollment's original tuition CHARGE.
    tuition_due = None
    for e in account_entries_for_enrollment(enrollment["id"]):
        if e["entry_type"] == "CHARGE" and e["charge_kind"] == "TUITION":
            tuition_due = e["due_date"]
            break
    post_entry(account["id"], "CHARGE_REVERSAL", r["amount_cents"],
               due_date=tuition_due, charge_kind="TUITION",
               enrollment_id=enrollment["id"], source_ref=r["id"],
               memo="Refund charge reversal")
    # If the reversal pushed the balance negative, post a REFUND_PAYOUT for
    # the absolute value so the account lands at exactly zero; the payout
    # amount is fixed at posting time from the pre-payout balance.
    balance = compute_balance(account_entries(account["id"]))
    if balance < 0:
        post_entry(account["id"], "REFUND_PAYOUT", -balance,
                   source_ref=r["id"], memo="Refund payout")
    r["status"] = "POSTED"
    touch(r)
    recompute_account(account, force_bump=True)
    return success(ser_refund(r))
