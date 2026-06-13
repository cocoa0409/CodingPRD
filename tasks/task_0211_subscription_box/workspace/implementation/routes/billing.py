"""Billing cycle + invoice read endpoints (PRD §3.12, §4)."""
from flask import Blueprint, request

from db import db
from common import serialize, must_exist, paginate
from middleware import authenticate, require_roles
from response import success, list_success

bp = Blueprint("billing", __name__)


@bp.get("/billing-cycles/<cid>")
def get_billing_cycle(cid):
    authenticate()
    require_roles("BillingOperator", "Subscriber", "CurationAdmin")
    cycle = must_exist(db.billing_cycles, cid, "BillingCycle")
    return success(serialize(cycle))


@bp.get("/billing-cycles")
def list_billing_cycles():
    authenticate()
    require_roles("BillingOperator", "Subscriber", "CurationAdmin")
    records = list(db.billing_cycles.values())
    sub_filter = request.args.get("subscription_id")
    if sub_filter is not None:
        records = [r for r in records if r["subscription_id"] == sub_filter]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    authenticate()
    require_roles("BillingOperator", "Subscriber", "CurationAdmin")
    inv = must_exist(db.invoices, iid, "Invoice")
    return success(serialize(inv))


@bp.get("/invoices")
def list_invoices():
    authenticate()
    require_roles("BillingOperator", "Subscriber", "CurationAdmin")
    records = list(db.invoices.values())
    subscriber_filter = request.args.get("subscriber_id")
    if subscriber_filter is not None:
        records = [r for r in records if r["subscriber_id"] == subscriber_filter]
    sub_filter = request.args.get("subscription_id")
    if sub_filter is not None:
        records = [r for r in records if r.get("subscription_id") == sub_filter]
    page, limit, offset, total = paginate(records)
    return list_success([serialize(r) for r in page], limit, offset, total)
