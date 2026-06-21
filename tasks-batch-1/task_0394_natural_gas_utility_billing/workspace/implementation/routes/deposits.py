"""Deposit endpoints (PRD §3.11)."""

from flask import Blueprint

from db import store
from errors import (
    ERR_INVALID_STATE,
    ERR_DEPOSIT_WAIVED_NOT_PAYABLE,
    ERR_DEPOSIT_REFUND_NOT_DUE,
    err,
)
from middleware import authenticate, require_role, require_account_ownership
from response import success
from services.common import (
    get_body,
    require_fields,
    require_enum,
    attach_common_fields,
    bump,
    paginate,
)
from services.serialize import view_deposit
from services import lookup, calc

bp = Blueprint("deposits", __name__)


@bp.route("/accounts/<account_id>/deposits", methods=["POST"])
def create_deposit(account_id):
    principal = authenticate()
    require_role(principal, {"CustomerService"})
    with store.lock:
        account = lookup.get_account(account_id)
        body = get_body()
        require_fields(body, ["reason"])
        reason = require_enum(body, "reason", {"NEW_SERVICE", "RECONNECT", "DELINQUENCY"})

        amount = calc.compute_deposit_requirement(account, reason)
        status = "WAIVED" if amount == 0 else "REQUIRED"
        rec = {
            "account_id": account_id,
            "amount_cents": amount,
            "reason": reason,
            "status": status,
        }
        attach_common_fields(rec)
        store.deposits[rec["id"]] = rec
        return success(view_deposit(rec), 201)


@bp.route("/accounts/<account_id>/deposits", methods=["GET"])
def list_deposits(account_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "Account"})
    account = lookup.get_account(account_id)
    require_account_ownership(principal, account_id)
    records = [d for d in store.deposits.values() if d["account_id"] == account_id]
    page, list_meta = paginate(records)
    return success([view_deposit(d) for d in page], 200, list_meta=list_meta)


@bp.route("/accounts/<account_id>/deposits/<deposit_id>/collect", methods=["POST"])
def collect_deposit(account_id, deposit_id):
    principal = authenticate()
    require_role(principal, {"CustomerService"})
    with store.lock:
        account = lookup.get_account(account_id)
        deposit = lookup.get_deposit_under_account(account_id, deposit_id)
        # PRD §3.11: a collect attempt on a 0-amount deposit (waived/exempt) is
        # rejected with ERR_DEPOSIT_WAIVED_NOT_PAYABLE. This specific error is
        # the PRD-named outcome for the amount-0 case (a waived deposit always
        # has amount 0), so it takes precedence over the generic state check.
        if deposit["amount_cents"] <= 0:
            raise err(ERR_DEPOSIT_WAIVED_NOT_PAYABLE, "Deposit amount is 0 and not payable")
        if deposit["status"] != "REQUIRED":
            raise err(ERR_INVALID_STATE, "Deposit is not REQUIRED")
        deposit["status"] = "HELD"
        bump(deposit)
        return success(view_deposit(deposit), 200)


@bp.route("/accounts/<account_id>/deposits/<deposit_id>/waive", methods=["POST"])
def waive_deposit(account_id, deposit_id):
    principal = authenticate()
    require_role(principal, {"CustomerService"})
    with store.lock:
        account = lookup.get_account(account_id)
        deposit = lookup.get_deposit_under_account(account_id, deposit_id)
        if deposit["status"] != "REQUIRED":
            raise err(ERR_INVALID_STATE, "Deposit is not REQUIRED")
        deposit["status"] = "WAIVED"
        bump(deposit)
        return success(view_deposit(deposit), 200)


@bp.route("/accounts/<account_id>/deposits/<deposit_id>/refund", methods=["POST"])
def refund_deposit(account_id, deposit_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    with store.lock:
        account = lookup.get_account(account_id)
        deposit = lookup.get_deposit_under_account(account_id, deposit_id)
        if deposit["status"] != "HELD":
            raise err(ERR_INVALID_STATE, "Deposit is not HELD")
        if account["consecutive_ontime_payments"] < calc.DEPOSIT_REFUND_ONTIME_COUNT:
            raise err(ERR_DEPOSIT_REFUND_NOT_DUE, "Account has not met the on-time payment threshold")
        deposit["status"] = "REFUNDED"
        bump(deposit)
        return success(view_deposit(deposit), 200)
