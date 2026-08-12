"""Margin accounts: reads and closure (PRD 3.9)."""
from flask import Blueprint, request

from authz import ANY_ROLE, CUSTOMER, check_customer_ownership, require_roles
from db import store
from errors import (
    account_closed,
    account_not_found,
    nonzero_balance,
    open_calls_exist,
    positions_exist,
)
from calc import NON_TERMINAL_CALL_STATES, positions_of_account, calls_of_account
from response import success
from serialize import ser_account
from store_ops import paginate, sorted_by_creation, touch

bp = Blueprint("accounts", __name__)


def get_account_or_404(account_id):
    account = store.accounts.get(account_id)
    if account is None:
        raise account_not_found()
    return account


@bp.route("/margin/accounts/<aid>", methods=["GET"])
def get_account(aid):
    require_roles(ANY_ROLE)
    return success(ser_account(get_account_or_404(aid)))


@bp.route("/margin/accounts", methods=["GET"])
def list_accounts():
    require_roles(ANY_ROLE)
    customer_id = request.args.get("customer_id")
    application_id = request.args.get("application_id")
    items = list(store.accounts.values())
    if customer_id is not None:
        items = [a for a in items if a["customer_id"] == customer_id]
    if application_id is not None:
        items = [a for a in items if a["application_id"] == application_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_account(a) for a in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/accounts/<aid>/close", methods=["POST"])
def close_account(aid):
    uid, _ = require_roles([CUSTOMER])
    account = get_account_or_404(aid)
    check_customer_ownership(uid, account["customer_id"])
    # PRD 3.9 pinned order: live -> flat -> call-free -> zero cash.
    if account["account_status"] == "CLOSED":
        raise account_closed()
    if any(p["quantity"] != 0 for p in positions_of_account(aid)):
        raise positions_exist()
    if any(c["call_status"] in NON_TERMINAL_CALL_STATES
           for c in calls_of_account(aid)):
        raise open_calls_exist()
    if account["cash_balance_cents"] != 0:
        raise nonzero_balance()
    account["account_status"] = "CLOSED"
    touch(account)
    return success(ser_account(account))
