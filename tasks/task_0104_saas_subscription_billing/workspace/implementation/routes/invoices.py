"""Invoice, line, payment, and revenue-schedule reads (PRD §3.6, §3.7, §3.8)."""
from flask import Blueprint, request

import errors
import serializers as S
from db import db
from middleware import authenticate, require_role, require_account_owner_match
from response import success
from util import parse_pagination, paginate, sort_by_created
from services import billing

bp = Blueprint("invoices", __name__)


def _get_invoice_or_404(invoice_id):
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise errors.not_found("Invoice not found")
    return inv


@bp.route("/accounts/<id>/invoices", methods=["GET"])
def list_account_invoices(id):
    role, user_id = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    account = db.accounts.get(id)
    if account is None:
        raise errors.not_found("Account not found")
    require_account_owner_match(role, user_id, id)

    sub_filter = request.args.get("subscription_id")
    limit, offset = parse_pagination()
    items = [i for i in db.invoices.values() if i["account_id"] == id
             and (sub_filter is None or i["subscription_id"] == sub_filter)]
    items = sort_by_created(items)
    page, pg = paginate(items, limit, offset)
    return success([S.ser_invoice(i) for i in page], is_array=True, pagination=pg)


@bp.route("/invoices/<id>", methods=["GET"])
def get_invoice(id):
    role, user_id = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    inv = _get_invoice_or_404(id)
    require_account_owner_match(role, user_id, inv["account_id"])
    return success(S.ser_invoice(inv))


@bp.route("/invoices/<id>/lines", methods=["GET"])
def list_invoice_lines(id):
    role, user_id = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    inv = _get_invoice_or_404(id)
    require_account_owner_match(role, user_id, inv["account_id"])
    limit, offset = parse_pagination()
    items = [l for l in db.invoice_lines.values() if l["invoice_id"] == id]
    items = sort_by_created(items)
    page, pg = paginate(items, limit, offset)
    return success([S.ser_invoice_line(l) for l in page], is_array=True, pagination=pg)


@bp.route("/invoices/<id>/payments", methods=["GET"])
def list_invoice_payments(id):
    role, user_id = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    inv = _get_invoice_or_404(id)
    require_account_owner_match(role, user_id, inv["account_id"])
    limit, offset = parse_pagination()
    items = [p for p in db.payments.values() if p["invoice_id"] == id]
    items = sort_by_created(items)
    page, pg = paginate(items, limit, offset)
    return success([S.ser_payment(p) for p in page], is_array=True, pagination=pg)


@bp.route("/invoices/<id>/revenue-schedule", methods=["GET"])
def get_revenue_schedule(id):
    role, user_id = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    inv = _get_invoice_or_404(id)
    require_account_owner_match(role, user_id, inv["account_id"])
    limit, offset = parse_pagination()
    items = [e for e in db.revenue_entries.values() if e["invoice_id"] == id]
    items = sort_by_created(items)
    page, pg = paginate(items, limit, offset)
    out = []
    for e in page:
        # recognized_to_date_cents computed against the current clock (PRD §3.8).
        e["recognized_to_date_cents"] = billing.recognized_to_date(e)
        out.append(S.ser_revenue_entry(e))
    return success(out, is_array=True, pagination=pg)
