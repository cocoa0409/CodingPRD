"""StorageInvoice read + pay endpoints (PRD §3.8). Creation is via advance-period."""
from flask import Blueprint, request

from db import db, touch
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    serialize, paginate, sort_by_created, get_storage_invoice_or_404,
)

bp = Blueprint("storage_invoices", __name__)

_ROLES = {"ComplianceOfficer", "AccountManager"}


@bp.get("/storage-invoices/<inv_id>")
def get_storage_invoice(inv_id):
    _, role = get_auth()
    require_role(role, _ROLES)
    i = get_storage_invoice_or_404(inv_id)
    return object_response(serialize(i), 200)


@bp.get("/storage-invoices")
def list_storage_invoices():
    _, role = get_auth()
    require_role(role, _ROLES)
    items = list(db.storage_invoices.values())
    account_id = request.args.get("account_id")
    period_index = request.args.get("period_index")
    status = request.args.get("status")
    if account_id is not None:
        items = [i for i in items if i["account_id"] == account_id]
    if period_index is not None:
        try:
            pi = int(period_index)
            items = [i for i in items if i["period_index"] == pi]
        except (ValueError, TypeError):
            items = []
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(i) for i in page], limit, offset, total, 200)


@bp.post("/storage-invoices/<inv_id>/pay")
def pay_storage_invoice(inv_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    i = get_storage_invoice_or_404(inv_id)
    i["status"] = "PAID"
    touch(i)
    return object_response(serialize(i), 200)
