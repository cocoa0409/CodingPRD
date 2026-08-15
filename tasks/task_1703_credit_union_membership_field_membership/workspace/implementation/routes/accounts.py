"""Share account and share transaction endpoints."""
from flask import Blueprint

import db
from auth import require_roles, check_member_owns, MEMBER, STAFF_ROLES
from errors import ApiError
from response import ok_object, paginate, now_iso
from serializers import serialize_account, serialize_transaction, serialize_payment
from services import calc, sweep
from services.sweep import new_id, bump
from validators import get_body, req_str, req_int, req_enum, req_date

bp = Blueprint("accounts", __name__)

ALL_READ = STAFF_ROLES | {MEMBER}


def get_account_or_404(aid):
    a = db.accounts.get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", f"share account {aid} not found")
    return a


def _check_account_ownership(uid, role, account):
    check_member_owns(uid, role, account["member_id"])


@bp.post("/credit-union/share-accounts")
def open_account():
    require_roles({"MembershipOfficer"})
    body = get_body()
    # Tier 4: syntactic
    member_id = req_str(body, "member_id")
    account_type = req_enum(body, "account_type", {"PRIMARY", "SUPPLEMENTAL"})
    initial_deposit_cents = req_int(body, "initial_deposit_cents")
    if initial_deposit_cents < 0:
        raise ApiError("ERR_VALIDATION_FAILED",
                       "initial_deposit_cents must be a non-negative integer")
    # Tier 5: existence
    member = db.members.get(member_id)
    if member is None:
        raise ApiError("ERR_NOT_FOUND", f"member {member_id} not found")
    # Tier 7: member posture
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", "member is not ACTIVE")
    # Tier 10: one PRIMARY per member
    if account_type == "PRIMARY":
        for a in db.accounts.values():
            if (a["member_id"] == member_id and a["account_type"] == "PRIMARY"
                    and a["status"] == "OPEN"):
                raise ApiError("ERR_PRIMARY_ACCOUNT_EXISTS",
                               "member already has a PRIMARY share account")
    # Tier 12: par value floor
    if account_type == "PRIMARY":
        charter = next(iter(db.charters.values()), None)
        if charter is not None and initial_deposit_cents < charter["par_value_cents"]:
            raise ApiError("ERR_BELOW_PAR_VALUE",
                           "PRIMARY opening deposit is below the charter par value")
    current_s = db.clock.current_date_str()
    account = {
        "id": new_id(),
        "member_id": member_id,
        "account_type": account_type,
        "balance_cents": 0,
        "opened_date": current_s,
        "status": "OPEN",
        "closed_date": None,
        "closure_reason": None,
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.accounts[account["id"]] = account
    sweep.write_system_tx(account, "DEPOSIT", initial_deposit_cents, current_s)
    return ok_object(serialize_account(account), 201)


@bp.get("/credit-union/share-accounts/<aid>")
def get_account(aid):
    uid, role = require_roles(ALL_READ)
    account = get_account_or_404(aid)
    _check_account_ownership(uid, role, account)
    return ok_object(serialize_account(account), 200)


@bp.post("/credit-union/share-accounts/<aid>/close")
def close_account(aid):
    require_roles({"MembershipOfficer"})
    account = get_account_or_404(aid)
    if account["status"] != "OPEN":
        raise ApiError("ERR_ACCOUNT_NOT_OPEN", "share account is not OPEN")
    if account["account_type"] == "PRIMARY":
        member = db.members.get(account["member_id"])
        if member is not None and member["status"] == "ACTIVE":
            raise ApiError("ERR_PRIMARY_ACCOUNT_REQUIRED",
                           "an ACTIVE member must retain a PRIMARY account")
    sweep.close_account(account, "MANUAL", db.clock.current_date_str())
    return ok_object(serialize_account(account), 200)


@bp.post("/credit-union/share-accounts/<aid>/transactions")
def post_transaction(aid):
    require_roles({"OperationsOfficer"})
    body = get_body()
    # Tier 4: syntactic
    kind = req_enum(body, "kind", {"DEPOSIT", "WITHDRAWAL"})
    amount_cents = req_int(body, "amount_cents")
    if amount_cents <= 0:
        raise ApiError("ERR_VALIDATION_FAILED", "amount_cents must be a positive integer")
    posted_date = req_date(body, "posted_date")
    # Tier 5: existence
    account = get_account_or_404(aid)
    # Tier 7: account state
    if account["status"] != "OPEN":
        raise ApiError("ERR_ACCOUNT_NOT_OPEN", "share account is not OPEN")
    # Tier 11: posting window
    current_s = db.clock.current_date_str()
    if posted_date < account["opened_date"] or posted_date > current_s:
        raise ApiError("ERR_INVALID_TRANSACTION_DATE",
                       "posted_date must be within [opened_date, current date]")
    # Tier 12: funds and par value
    if kind == "WITHDRAWAL":
        if account["account_type"] == "PRIMARY":
            charter = next(iter(db.charters.values()), None)
            par = charter["par_value_cents"] if charter is not None else 0
            if account["balance_cents"] - amount_cents < par:
                raise ApiError("ERR_PAR_VALUE_BREACH",
                               "withdrawal would leave a PRIMARY account below par value")
        else:
            if account["balance_cents"] - amount_cents < 0:
                raise ApiError("ERR_INSUFFICIENT_FUNDS",
                               "withdrawal exceeds the account balance")
    tx = {
        "id": new_id(),
        "share_account_id": account["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "posted_date": posted_date,
        "running_balance_cents": 0,
        "origin": "MANUAL",
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.transactions[tx["id"]] = tx
    calc.replay_account(account)
    bump(account)
    return ok_object(serialize_transaction(tx), 201)


@bp.get("/credit-union/share-accounts/<aid>/transactions")
def list_transactions(aid):
    uid, role = require_roles(ALL_READ)
    account = get_account_or_404(aid)
    _check_account_ownership(uid, role, account)
    items = calc.account_txs(aid)
    return paginate([serialize_transaction(t) for t in items])


@bp.get("/credit-union/share-accounts/<aid>/dividend-payments")
def list_account_payments(aid):
    uid, role = require_roles(ALL_READ)
    account = get_account_or_404(aid)
    _check_account_ownership(uid, role, account)
    items = [p for p in db.payments.values() if p["share_account_id"] == aid]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return paginate([serialize_payment(p) for p in items])
