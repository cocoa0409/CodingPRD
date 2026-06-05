from flask import Blueprint, request

import errors
from errors import err
from db import db
from models import touch, serialize
from middleware import get_identity, require_role
from helpers import (lookup, parse_pagination, paginate, sort_by_created,
                     require_tenant_owns_lease)
from response import success, list_response
from services import domain

bp = Blueprint("invoices", __name__)


@bp.get("/invoices/<invoice_id>")
def get_invoice(invoice_id):
    user_id, role = get_identity()
    inv = lookup(db.invoices, invoice_id, "invoice")
    lease = db.leases.get(inv["lease_id"])
    if lease is not None:
        require_tenant_owns_lease(user_id, role, lease)
    return success(serialize(inv), 200)


@bp.get("/invoices")
def list_invoices():
    user_id, role = get_identity()
    limit, offset = parse_pagination()
    items = list(db.invoices.values())
    lease_id = request.args.get("lease_id")
    status = request.args.get("status")
    if lease_id is not None:
        items = [i for i in items if i["lease_id"] == lease_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if role == "Tenant":
        owned = {l["id"] for l in db.leases.values() if l["tenant_id"] == user_id}
        items = [i for i in items if i["lease_id"] in owned]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize(i) for i in page], total, limit, offset)


@bp.post("/invoices/<invoice_id>/waive")
def waive_invoice(invoice_id):
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    inv = lookup(db.invoices, invoice_id, "invoice")

    if inv["status"] not in ("OPEN", "PARTIAL", "OVERDUE"):
        raise err(errors.ERR_INVALID_STATE, "Invoice must be OPEN, PARTIAL, or OVERDUE to waive")

    lease = db.leases.get(inv["lease_id"])
    unpaid = inv["total_amount_cents"] - inv["amount_paid_cents"]
    inv["status"] = "WAIVED"
    touch(inv)
    if lease is not None and unpaid != 0:
        domain.append_ledger(lease, "CREDIT", -unpaid, "INVOICE", inv["id"])
        touch(lease)
    return success(serialize(inv), 200)
