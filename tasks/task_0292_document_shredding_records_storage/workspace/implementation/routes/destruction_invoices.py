"""DestructionInvoice read + pay endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import db, touch
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    serialize, paginate, sort_by_created, get_destruction_invoice_or_404,
)

bp = Blueprint("destruction_invoices", __name__)

_ROLES = {"ComplianceOfficer", "AccountManager"}


@bp.get("/destruction-invoices/<inv_id>")
def get_destruction_invoice(inv_id):
    _, role = get_auth()
    require_role(role, _ROLES)
    i = get_destruction_invoice_or_404(inv_id)
    return object_response(serialize(i), 200)


@bp.get("/destruction-invoices")
def list_destruction_invoices():
    _, role = get_auth()
    require_role(role, _ROLES)
    items = list(db.destruction_invoices.values())
    order_id = request.args.get("order_id")
    account_id = request.args.get("account_id")
    certificate_id = request.args.get("certificate_id")
    status = request.args.get("status")
    if order_id is not None:
        items = [i for i in items if i["order_id"] == order_id]
    if account_id is not None:
        items = [i for i in items if i["account_id"] == account_id]
    if certificate_id is not None:
        items = [i for i in items if i["certificate_id"] == certificate_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(i) for i in page], limit, offset, total, 200)


@bp.post("/destruction-invoices/<inv_id>/pay")
def pay_destruction_invoice(inv_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    i = get_destruction_invoice_or_404(inv_id)
    i["status"] = "PAID"
    touch(i)
    return object_response(serialize(i), 200)
