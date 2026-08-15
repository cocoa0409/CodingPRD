"""AccountTransaction endpoints (PRD §3.1).

Customer-facing postings only: DEPOSIT | WITHDRAWAL | FEDERAL_BENEFIT_DEPOSIT.
Credits post under any restriction; WITHDRAWAL is gated by restriction before
funds sufficiency (PRD §2.10: a restricted, unaffordable withdrawal reports
ERR_ACCOUNT_RESTRICTED).
"""

from datetime import date

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_ACCOUNT_RESTRICTED,
    ERR_INSUFFICIENT_AVAILABLE_FUNDS,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import paginate, parse_pagination, success_list, success_object
from serialization import transaction_view
from services.account import (
    CLIENT_TXN_TYPES,
    derived_totals,
    get_account_or_404,
    post_transaction,
    touch_account,
)

bp = Blueprint("transactions", __name__)


@bp.post("/bank/accounts/<account_id>/transactions")
def post_customer_transaction(account_id):
    require_roles(["OpsOfficer", "System"])
    acct = get_account_or_404(account_id)
    body = request.get_json(silent=True) or {}

    txn_type = body.get("txn_type")
    if txn_type not in CLIENT_TXN_TYPES:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "txn_type must be one of DEPOSIT, WITHDRAWAL, FEDERAL_BENEFIT_DEPOSIT",
        )
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_cents must be a positive integer")
    customer_initiated = body.get("customer_initiated", False)
    if not isinstance(customer_initiated, bool):
        raise ApiError(ERR_INVALID_REQUEST, "customer_initiated must be a boolean")
    posted_date = body.get("posted_date")
    if posted_date is None:
        posted_date = db.clock_date_str()
    else:
        try:
            posted_date = date.fromisoformat(posted_date).isoformat()
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "posted_date must be a YYYY-MM-DD date")

    if acct["lifecycle_status"] == "CLOSED":
        from errors import ERR_INVALID_STATE
        raise ApiError(ERR_INVALID_STATE, "Account is CLOSED")

    # Compliance gate first (tier 6), funds sufficiency last (tier 9).
    if txn_type == "WITHDRAWAL" and acct["restriction_status"] != "NONE":
        raise ApiError(ERR_ACCOUNT_RESTRICTED, "Withdrawals are blocked while a restriction is in force")
    if customer_initiated and acct["lifecycle_status"] in ("DORMANT", "ESCHEAT_PENDING"):
        if acct["restriction_status"] != "NONE":
            raise ApiError(ERR_ACCOUNT_RESTRICTED, "A restricted dormant account cannot be reactivated")

    if txn_type == "WITHDRAWAL":
        _, available = derived_totals(account_id)
        if amount > available:
            raise ApiError(ERR_INSUFFICIENT_AVAILABLE_FUNDS, "Withdrawal exceeds available_balance_cents")

    txn = post_transaction(acct, txn_type, amount, customer_initiated, posted_date)

    if customer_initiated:
        acct["last_customer_activity_date"] = posted_date
        if acct["lifecycle_status"] in ("DORMANT", "ESCHEAT_PENDING"):
            # Reactivation (PRD §3.1): the dormancy episode resets.
            acct["lifecycle_status"] = "OPEN"
            acct["dormant_since_date"] = None
            acct["fees_assessed_count"] = 0

    touch_account(acct)
    return success_object(transaction_view(txn), status=201)


@bp.get("/bank/accounts/<account_id>/transactions")
def list_transactions(account_id):
    require_roles(["OpsOfficer", "OpsManager", "Auditor", "System"])
    get_account_or_404(account_id)
    limit, offset = parse_pagination(request.args)
    txn_type = request.args.get("txn_type")

    items = [t for t in db.transactions.values() if t["account_id"] == account_id]
    items.sort(key=lambda t: t["_seq"])
    if txn_type is not None:
        items = [t for t in items if t["txn_type"] == txn_type]
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([transaction_view(t) for t in page], total, limit, offset)
