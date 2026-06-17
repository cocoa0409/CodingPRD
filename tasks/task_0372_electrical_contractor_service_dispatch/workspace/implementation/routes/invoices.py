"""Invoice read endpoints (PRD §3.7). Invoices are created by the job invoice
transition; only GET endpoints are exposed here."""
from flask import Blueprint, request

import db
import response
from errors import err
from helpers import (paginate, parse_pagination, serialize, serialize_list,
                     sort_by_created)
from middleware import get_identity, require_roles

bp = Blueprint("invoices", __name__)


@bp.get("/v1/invoices/<invoice_id>")
def get_invoice(invoice_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    record = db.invoices.get(invoice_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Invoice not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/invoices")
def list_invoices():
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    limit, offset = parse_pagination()
    job_id = request.args.get("job_id")

    items = list(db.invoices.values())
    if job_id is not None:
        items = [iv for iv in items if iv["job_id"] == job_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)
