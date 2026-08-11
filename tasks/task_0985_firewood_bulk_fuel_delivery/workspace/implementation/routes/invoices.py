"""Invoice endpoints (PRD §3.8)."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_list, success_object
from services.domain import serialize_invoice, serialize_payment_event
from util import paginate, parse_pagination, touch

bp = Blueprint("invoices", __name__)


def _get_invoice_or_404(iid):
    inv = db.invoices.get(iid)
    if not inv:
        raise errors.not_found(f"Invoice {iid} not found")
    return inv


@bp.get("/api/v1/invoices/<iid>")
def get_invoice(iid):
    auth = require_roles("CustomerService", "OperationsManager", "Customer")
    inv = _get_invoice_or_404(iid)
    if auth.is_customer():
        order = db.orders.get(inv.get("order_id")) if inv.get("order_id") else None
        owner = order["customer_id"] if order else inv.get("customer_id")
        if owner != auth.user_id:
            raise errors.unauthorized()
    return success_object(serialize_invoice(inv))


@bp.get("/api/v1/invoices")
def list_invoices():
    require_roles("CustomerService", "OperationsManager")
    limit, offset = parse_pagination()
    items = list(db.invoices.values())
    oid = request.args.get("order_id")
    if oid is not None:
        items = [i for i in items if str(i.get("order_id")) == oid]
    st = request.args.get("status")
    if st is not None:
        items = [i for i in items if i.get("status") == st]
    cid = request.args.get("customer_id")
    if cid is not None:
        def _owner(inv):
            order = db.orders.get(inv.get("order_id")) if inv.get("order_id") else None
            if order:
                return order["customer_id"]
            return inv.get("customer_id")
        items = [i for i in items if _owner(i) == cid]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_invoice(i) for i in page], total, limit, offset)


@bp.post("/api/v1/invoices/<iid>/void")
def void_invoice(iid):
    require_roles("OperationsManager")
    inv = _get_invoice_or_404(iid)
    order = db.orders.get(inv.get("order_id")) if inv.get("order_id") else None
    if inv["status"] != "OPEN" or inv["paid_cents"] != 0 or not order or order["fulfillment_status"] != "CANCELLED":
        raise errors.invoice_not_voidable()
    inv["status"] = "VOID"
    touch(inv)
    return success_object(serialize_invoice(inv))


@bp.get("/api/v1/invoices/<iid>/payment-events")
def list_payment_events(iid):
    require_roles("CustomerService", "OperationsManager")
    _get_invoice_or_404(iid)
    limit, offset = parse_pagination()
    items = [e for e in db.payment_events.values() if e["invoice_id"] == iid]
    ek = request.args.get("event_kind")
    if ek is not None:
        items = [e for e in items if e["event_kind"] == ek]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_payment_event(e) for e in page], total, limit, offset)
