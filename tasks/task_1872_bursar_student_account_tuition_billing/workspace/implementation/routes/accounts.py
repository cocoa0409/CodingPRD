from decimal import Decimal
from flask import Blueprint

from db import store, clock_date
from errors import (err, ERR_ACCOUNT_NOT_FOUND, ERR_ACCOUNT_STATE_INVALID,
                    ERR_COLLECTIONS_STATE_INVALID, ERR_NO_BALANCE_DUE,
                    ERR_SEGREGATION_OF_DUTIES, ERR_FORBIDDEN)
from middleware import auth_context, require_roles, forbid
from response import success, json_body, req_enum, list_response
from serialize import ser_account, ser_ledger_entry
from services.core import post_entry, account_entries, recompute_account
from services.domain import round_half_up_cents, cancel_plan

bp = Blueprint("accounts", __name__)

COLLECTIONS_FEE_PCT = Decimal("0.05")


def _load_account(aid, uid, role):
    a = store.accounts.get(aid)
    if a is None:
        raise err(ERR_ACCOUNT_NOT_FOUND, "Account not found")
    if role == "Student" and a["student_id"] != uid:
        forbid()
    return a


@bp.get("/bursar/accounts/<aid>")
def get_account(aid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    a = _load_account(aid, uid, role)
    return success(ser_account(a))


@bp.get("/bursar/accounts/<aid>/ledger")
def account_ledger(aid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    a = _load_account(aid, uid, role)
    return list_response(account_entries(a["id"]), ser_ledger_entry)


@bp.post("/bursar/accounts/<aid>/send-to-collections")
def send_to_collections(aid):
    uid, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    a = _load_account(aid, uid, role)
    if a["status"] != "PAST_DUE":
        raise err(ERR_COLLECTIONS_STATE_INVALID,
                  "send-to-collections requires the account to be PAST_DUE")
    if a["balance_cents"] <= 0:
        raise err(ERR_NO_BALANCE_DUE, "Account carries no positive balance")
    fee = round_half_up_cents(Decimal(a["balance_cents"]) * COLLECTIONS_FEE_PCT)
    post_entry(a["id"], "COLLECTIONS_FEE", fee, due_date=clock_date().isoformat(),
               source_ref=a["id"], memo="Collections placement fee")
    a["status"] = "COLLECTIONS"
    recompute_account(a, force_bump=True)
    return success(ser_account(a))


@bp.post("/bursar/accounts/<aid>/write-off")
def write_off(aid):
    uid, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    a = _load_account(aid, uid, role)
    body = json_body()
    action = req_enum(body, "action", ("REQUEST", "APPROVE", "REJECT"))

    # APPROVE and REJECT are BursarManager-only dispositions.
    if action in ("APPROVE", "REJECT") and role != "BursarManager":
        raise err(ERR_FORBIDDEN, "Write-off approval and rejection are manager-only")

    if action == "REQUEST":
        if a["status"] != "COLLECTIONS" or a["writeoff_status"] != "NONE":
            raise err(ERR_COLLECTIONS_STATE_INVALID,
                      "Write-off request requires COLLECTIONS status and no pending disposition")
        a["writeoff_status"] = "PENDING"
        a["writeoff_requester_id"] = uid
        recompute_account(a, force_bump=True)
        return success(ser_account(a))

    if a["status"] != "COLLECTIONS" or a["writeoff_status"] != "PENDING":
        raise err(ERR_COLLECTIONS_STATE_INVALID,
                  "Write-off approval/rejection requires a pending request on a COLLECTIONS account")

    if action == "REJECT":
        a["writeoff_status"] = "REJECTED"
        recompute_account(a, force_bump=True)
        return success(ser_account(a))

    # APPROVE: segregation of duties — approver must differ from requester.
    if uid == a["writeoff_requester_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "Write-off approver must differ from the requester")
    post_entry(a["id"], "WRITE_OFF", a["balance_cents"], source_ref=a["id"],
               memo="Write-off of uncollectible balance")
    a["writeoff_status"] = "APPROVED"
    a["status"] = "WRITTEN_OFF"
    for p in list(store.plans.values()):
        if p["account_id"] == a["id"] and p["status"] in ("ACTIVE", "DEFAULTED"):
            cancel_plan(p)
    recompute_account(a, force_bump=True)
    return success(ser_account(a))
