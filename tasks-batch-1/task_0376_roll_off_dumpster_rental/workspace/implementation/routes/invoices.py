"""Invoice endpoints (PRD section 3.10)."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import get_invoice, check_invoice_owner, paginate
from middleware import require_auth, require_role
from response import success
from serialize import invoice as ser

import validate

bp = Blueprint("invoices", __name__)


def _recompute_account(account_id):
    """Bump the account's version/updated_at because its ledger changed.
    outstanding_cents / available_credit_cents are computed on read."""
    account = db.contractor_accounts.get(account_id)
    if account is not None:
        db.touch(account)


@bp.get("/invoices")
def list_invoices():
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "BillingClerk", "Contractor"])
    limit, offset = validate.get_pagination()
    records = list(db.invoices.values())
    if role == "Contractor":
        records = [r for r in records if r["account_id"] == user_id]
    order_id = request.args.get("order_id")
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if order_id is not None:
        records = [r for r in records if r["order_id"] == order_id]
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate(records, ser, limit, offset)


@bp.get("/invoices/<invoice_id>")
def get_invoice_ep(invoice_id):
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "BillingClerk", "Contractor"])
    rec = get_invoice(invoice_id)
    check_invoice_owner(rec, role, user_id)
    return success(ser(rec), status=200)


@bp.post("/invoices/<invoice_id>/pay")
def pay_invoice(invoice_id):
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    rec = get_invoice(invoice_id)
    if rec["status"] != "ISSUED":
        raise err("ERR_INVOICE_NOT_ISSUED", "Invoice is not ISSUED")
    rec["status"] = "PAID"
    db.touch(rec)
    _recompute_account(rec["account_id"])
    return success(ser(rec), status=200)


@bp.post("/invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    rec = get_invoice(invoice_id)
    if rec["status"] != "ISSUED":
        raise err("ERR_INVOICE_NOT_ISSUED", "Invoice is not ISSUED")
    rec["status"] = "VOID"
    db.touch(rec)
    _recompute_account(rec["account_id"])
    return success(ser(rec), status=200)
