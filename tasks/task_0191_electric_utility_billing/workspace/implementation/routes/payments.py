"""Payment endpoints: post (waterfall + arrears clear + disconnect cancel) and
reverse (PRD §3.5)."""
from flask import Blueprint, request

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles, require_owner
from response import success
from services import serializers as ser
from services.common import (
    check_enum,
    get_json_body,
    paginate,
    parse_pagination,
    require_fields,
    require_int,
)
from services.ledger import (
    apply_payment_waterfall,
    cancel_scheduled_disconnect,
    compute_financial_status,
    recompute_amount_paid_from_postings,
    recompute_oldest_unpaid,
)

bp = Blueprint("payments", __name__)

READ_ROLES = {"BillingOperator", "Customer"}
METHODS = {"ACH", "CARD", "CASH"}


@bp.route("/payments", methods=["POST"])
def create_payment():
    user_id, role = authenticate()
    require_roles(role, {"Customer", "BillingOperator"})
    body = get_json_body()
    require_fields(body, ["account_id", "amount_cents"])
    account_id = body["account_id"]
    amount_cents = require_int(body, "amount_cents")
    method = body.get("method", "ACH")
    if method is None:
        method = "ACH"
    check_enum(method, METHODS, "method")

    account = db.accounts.get(account_id)
    if account is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced account does not exist.")

    # Customer may only pay their own account.
    require_owner(role, user_id, account_id)

    # Amount must be strictly positive (ERR_INVALID_PAYMENT per PRD §3.5).
    if amount_cents <= 0:
        raise err("ERR_INVALID_PAYMENT", "Payment amount must be > 0.")

    rec = base_record()
    rec.update({
        "account_id": account_id,
        "amount_cents": amount_cents,
        "method": method,
        "status": "POSTED",
        "allocations": [],
    })

    # Waterfall allocation (mutates bills + reduces account balance).
    allocations = apply_payment_waterfall(account, amount_cents)
    rec["allocations"] = allocations
    db.payments[rec["id"]] = rec

    # Re-age against the post-allocation unpaid set.
    recompute_oldest_unpaid(account)
    new_status = compute_financial_status(account)
    cleared = new_status != "IN_ARREARS" and account["financial_status"] == "IN_ARREARS"
    status_changed = new_status != account["financial_status"]
    account["financial_status"] = new_status

    # If arrears cleared while a disconnect is still scheduled, cascade-cancel it
    # and return service to ACTIVE (PRD §3.5).
    if new_status != "IN_ARREARS":
        cancel_scheduled_disconnect(account)

    # The payment itself plus any status changes bump the account version once.
    touch(account)
    return success(ser.payment(rec), status=201)


@bp.route("/payments/<payment_id>/reverse", methods=["POST"])
def reverse_payment(payment_id):
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    payment = db.payments.get(payment_id)
    if payment is None:
        raise err("ERR_NOT_FOUND", "Payment not found.")
    if payment["status"] != "POSTED":
        raise err("ERR_INVALID_PAYMENT", "Only a POSTED payment can be reversed.")

    account = db.accounts.get(payment["account_id"])

    # Move to REVERSED first so its allocations no longer count.
    payment["status"] = "REVERSED"
    touch(payment)

    # Restore account balance by the full reversed amount.
    account["balance_cents"] += payment["amount_cents"]

    # Recompute amount_paid/status on each bill this payment had touched, using
    # only the remaining POSTED allocations.
    touched_bill_ids = {a["bill_id"] for a in payment.get("allocations", [])}
    for bid in touched_bill_ids:
        bill = db.bills.get(bid)
        if bill is not None:
            recompute_amount_paid_from_postings(bill)
            touch(bill)

    # Re-age financial_status against the now-larger unpaid balance.
    recompute_oldest_unpaid(account)
    new_status = compute_financial_status(account)
    account["financial_status"] = new_status
    touch(account)
    return success(ser.payment(payment), status=200)


@bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.payments.get(payment_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Payment not found.")
    require_owner(role, user_id, rec["account_id"])
    return success(ser.payment(rec), status=200)


@bp.route("/payments", methods=["GET"])
def list_payments():
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = list(db.payments.values())
    if role == "Customer":
        items = [p for p in items if p["account_id"] == user_id]
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, pagination = paginate(items)
    return success([ser.payment(p) for p in page], status=200, pagination=pagination)
