from flask import Blueprint
import errors
from errors import err
from db import db, init_common, touch, now_iso
from middleware import get_auth, require_roles
from response import success
from util import (get_body, require_str, require_int, require_bool, require_enum,
                  paginate, sorted_by_created)
from serialize import public, public_list
from services import core

bp = Blueprint("accounts", __name__)


def _owner_check_account(role, user_id, account):
    if role == "AccountHolder" and account["id"] != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER,
                  "AccountHolder does not own this account")


def _get_account_or_404(account_id):
    acc = db.accounts.get(account_id)
    if acc is None:
        raise err(errors.ERR_NOT_FOUND, "Account not found")
    return acc


@bp.post("/etc/accounts")
def create_account():
    _, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator"})
    body = get_body()

    holder_name = require_str(body, "holder_name")
    home_state_code = require_str(body, "home_state_code")
    low_threshold = require_int(body, "low_balance_threshold_cents", required=False,
                                default=1000, min_value=0)
    auto_reload = require_bool(body, "auto_reload_enabled", required=False, default=False)
    reload_policy = require_enum(body, "reload_policy", {"FIXED", "RESTORE_TO_TARGET"},
                                 required=False, default="FIXED")
    reload_amount = require_int(body, "reload_amount_cents", required=False, default=4000)
    target_balance = require_int(body, "target_balance_cents", required=False, default=5000)

    if auto_reload and reload_amount is not None and reload_amount <= 0:
        raise err(errors.ERR_VALIDATION,
                  "reload_amount_cents must be > 0 when auto_reload_enabled")
    if reload_policy == "RESTORE_TO_TARGET" and target_balance <= low_threshold:
        raise err(errors.ERR_VALIDATION,
                  "target_balance_cents must be > low_balance_threshold_cents")

    acc = {
        "holder_name": holder_name,
        "home_state_code": home_state_code,
        "status": "ACTIVE",
        "balance_cents": 0,
        "low_balance_threshold_cents": low_threshold,
        "auto_reload_enabled": auto_reload,
        "reload_amount_cents": reload_amount,
        "reload_policy": reload_policy,
        "target_balance_cents": target_balance,
        "outstanding_fines_cents": 0,
    }
    init_common(acc)
    db.accounts[acc["id"]] = acc
    return success(public(acc), status=201)


@bp.get("/etc/accounts/<account_id>")
def get_account(account_id):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    acc = _get_account_or_404(account_id)
    _owner_check_account(role, user_id, acc)
    return success(public(acc))


@bp.post("/etc/accounts/<account_id>/credit")
def credit_account(account_id):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator"})
    acc = _get_account_or_404(account_id)
    _owner_check_account(role, user_id, acc)
    body = get_body()
    amount = require_int(body, "amount_cents")
    core.append_ledger(acc, "RELOAD_CREDIT", amount)
    touch(acc)
    return success(public(acc))


@bp.post("/etc/accounts/<account_id>/suspend")
def suspend_account(account_id):
    _, role = get_auth()
    require_roles(role, {"TollOperator"})
    acc = _get_account_or_404(account_id)
    if acc["status"] not in ("ACTIVE", "DELINQUENT"):
        raise err(errors.ERR_INVALID_STATE, "Account not in a suspendable state")
    get_body()  # optional reason; not stored
    acc["status"] = "SUSPENDED"
    touch(acc)
    # Cascade: deactivate BOUND transponders, end their ACTIVE bindings
    ts = now_iso()
    for t in db.transponders.values():
        if t["account_id"] == account_id and t["status"] == "BOUND":
            t["status"] = "DEACTIVATED"
            touch(t)
            for b in db.transponder_bindings.values():
                if b["transponder_id"] == t["id"] and b["status"] == "ACTIVE":
                    b["status"] = "ENDED"
                    b["effective_to"] = ts
                    touch(b)
    return success(public(acc))


@bp.post("/etc/accounts/<account_id>/reinstate")
def reinstate_account(account_id):
    _, role = get_auth()
    require_roles(role, {"TollOperator"})
    acc = _get_account_or_404(account_id)
    if acc["status"] != "SUSPENDED":
        raise err(errors.ERR_INVALID_STATE, "Account is not SUSPENDED")
    if acc["outstanding_fines_cents"] != 0:
        raise err(errors.ERR_INVALID_STATE,
                  "Cannot reinstate with outstanding fines")
    acc["status"] = "ACTIVE"
    touch(acc)
    return success(public(acc))


@bp.post("/etc/accounts/<account_id>/close")
def close_account(account_id):
    _, role = get_auth()
    require_roles(role, {"TollOperator"})
    acc = _get_account_or_404(account_id)
    if acc["status"] != "SUSPENDED":
        raise err(errors.ERR_INVALID_STATE, "Account must be SUSPENDED to close")
    if acc["balance_cents"] != 0 or acc["outstanding_fines_cents"] != 0:
        raise err(errors.ERR_BALANCE_NONZERO,
                  "Account close requires zero balance and zero outstanding fines")
    acc["status"] = "CLOSED"
    touch(acc)
    return success(public(acc))


@bp.get("/etc/accounts/<account_id>/ledger-entries")
def list_account_ledger(account_id):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    acc = _get_account_or_404(account_id)
    _owner_check_account(role, user_id, acc)
    items = [e for e in db.ledger_entries.values() if e["account_id"] == account_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)
