"""Payment routes and the collection waterfall (PRD §3.6)."""
from flask import Blueprint

import db
import middleware
from response import object_response, array_response
from services import lookup, ledger
from services.common import (
    get_json_body, require_int, require_enum, public, public_list,
    parse_pagination, paginate,
)

bp = Blueprint("payments", __name__)


@bp.post("/accounts/<account_id>/payments")
def create_payment(account_id):
    middleware.require_role({"Customer", "BillingClerk"})
    account = lookup.account(account_id)
    middleware.require_owner(account_id)
    body = get_json_body()

    amount = require_int(body, "amount_cents", minimum=1)  # > 0
    method = require_enum(body, "method", {"CARD", "ACH", "CASH"}, default="ACH")

    rec = db.make_record({
        "account_id": account_id,
        "amount_cents": amount,
        "applied_to_bill_id": None,
        "method": method,
    }, append_only=True)
    db.payments[rec["id"]] = rec

    # Waterfall: apply oldest-first; flip covered bills POSTED -> PAID.
    ledger.apply_payment_waterfall(account, rec)
    ledger.reconcile(account)

    # Collections posture resolution (PRD §3.6).
    _resolve_posture_after_payment(account)

    return object_response(public(rec), 201)


def _resolve_posture_after_payment(account):
    """Resolve collections posture after the waterfall (PRD §3.6).

    Rule 1 (general): if resulting past_due_cents is zero, billing_status
    returns to CURRENT.
    Rule 2 (stronger cascade): if the account is SHUTOFF_PENDING and past_due
    reached zero while every shutoff order is still merely SCHEDULED (none
    EXECUTED), all those SCHEDULED orders are cancelled and the account returns
    to CURRENT.
    """
    if account["past_due_cents"] != 0:
        return

    # Stronger cascade — fires only when SHUTOFF_PENDING and no order EXECUTED.
    if account["billing_status"] == "SHUTOFF_PENDING":
        orders = ledger.account_shutoffs(account["id"])
        active_orders = [o for o in orders if o["status"] in ("SCHEDULED", "EXECUTED")]
        if active_orders and all(o["status"] == "SCHEDULED" for o in active_orders):
            for o in active_orders:
                o["status"] = "CANCELLED"
                db.touch(o)

    # General rule: return to CURRENT from PAST_DUE / SHUTOFF_PENDING.
    # DELINQUENT_PROTECTED is governed by assistance, not payment.
    if account["billing_status"] in ("PAST_DUE", "SHUTOFF_PENDING"):
        account["billing_status"] = "CURRENT"
    ledger.reconcile(account)


@bp.get("/accounts/<account_id>/payments")
def list_payments(account_id):
    middleware.require_role({"BillingClerk", "Customer"})
    lookup.account(account_id)
    middleware.require_owner(account_id)
    limit, offset = parse_pagination()

    records = [p for p in db.payments.values() if p["account_id"] == account_id]
    window, total = paginate(records, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)
