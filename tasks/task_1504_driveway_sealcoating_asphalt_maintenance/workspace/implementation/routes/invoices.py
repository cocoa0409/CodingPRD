"""Invoice endpoints."""

from flask import Blueprint, request

from clock import now_iso_ms
from db import DB
from middleware import (
    require_role, get_json_body, require_fields, check_unknown_fields,
    paginate, err, touch,
)
from response import success_object, success_list
from errors import (
    ERR_INVOICE_NOT_FOUND, ERR_NOT_RESOURCE_OWNER, ERR_INVOICE_NOT_ISSUABLE,
    ERR_INVOICE_NOT_PAYABLE, ERR_PAYMENT_AMOUNT_MISMATCH, ERR_INVALID_REQUEST,
)

bp = Blueprint("invoices", __name__)


def serialize_invoice(inv):
    return {
        "id": inv["id"],
        "work_order_id": inv["work_order_id"],
        "line_items": inv["line_items"],
        "subtotal_cents": inv["subtotal_cents"],
        "fuel_surcharge_cents": inv["fuel_surcharge_cents"],
        "total_cents": inv["total_cents"],
        "issued_at": inv["issued_at"],
        "paid_at": inv["paid_at"],
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def _invoice_property(inv):
    wo = DB.work_orders.get(inv["work_order_id"])
    if wo is None:
        return None
    return DB.properties.get(wo["property_id"])


@bp.get("/api/invoices")
def list_invoices():
    user_id, role = require_role("OfficeAdmin", "Customer")
    items = list(DB.invoices.values())
    if role == "Customer":
        own_props = {p["id"] for p in DB.properties.values() if p["customer_id"] == user_id}
        own_wos = {w["id"] for w in DB.work_orders.values() if w["property_id"] in own_props}
        items = [i for i in items if i["work_order_id"] in own_wos]
    wo_filter = request.args.get("work_order_id")
    status_filter = request.args.get("status")
    if wo_filter:
        items = [i for i in items if i["work_order_id"] == wo_filter]
    if status_filter:
        items = [i for i in items if i["status"] == status_filter]
    items.sort(key=lambda i: i["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_invoice(i) for i in page], limit, offset, total)


@bp.get("/api/invoices/<invoiceId>")
def get_invoice(invoiceId):
    user_id, role = require_role("OfficeAdmin", "Customer")
    inv = DB.invoices.get(invoiceId)
    if inv is None:
        raise err(ERR_INVOICE_NOT_FOUND, 404, "Invoice id does not exist")
    if role == "Customer":
        prop = _invoice_property(inv)
        if prop is None or prop["customer_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, 403,
                      "Customer acting on a resource owned by a different customer")
    return success_object(serialize_invoice(inv))


@bp.post("/api/invoices/<invoiceId>/issue")
def issue_invoice(invoiceId):
    require_role("OfficeAdmin")
    inv = DB.invoices.get(invoiceId)
    if inv is None:
        raise err(ERR_INVOICE_NOT_FOUND, 404, "Invoice id does not exist")
    if inv["status"] != "DRAFT":
        raise err(ERR_INVOICE_NOT_ISSUABLE, 409, "issue requires DRAFT")
    inv["status"] = "ISSUED"
    inv["issued_at"] = now_iso_ms()
    touch(inv)
    wo = DB.work_orders.get(inv["work_order_id"])
    if wo is not None:
        wo["billing_status"] = "INVOICED"
        touch(wo)
    return success_object(serialize_invoice(inv))


@bp.post("/api/invoices/<invoiceId>/pay")
def pay_invoice(invoiceId):
    user_id, role = require_role("OfficeAdmin", "Customer")
    inv = DB.invoices.get(invoiceId)
    if inv is None:
        raise err(ERR_INVOICE_NOT_FOUND, 404, "Invoice id does not exist")
    if role == "Customer":
        prop = _invoice_property(inv)
        if prop is None or prop["customer_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, 403,
                      "Customer acting on a resource owned by a different customer")
    if inv["status"] != "ISSUED":
        raise err(ERR_INVOICE_NOT_PAYABLE, 409, "pay requires ISSUED")
    body = get_json_body()
    check_unknown_fields(body, {"amount_cents"})
    require_fields(body, ["amount_cents"])
    amount = body["amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise err(ERR_INVALID_REQUEST, 400, "amount_cents must be an integer")
    if amount != inv["total_cents"]:
        raise err(ERR_PAYMENT_AMOUNT_MISMATCH, 422,
                  "amount_cents differs from invoice total_cents")
    inv["status"] = "PAID"
    inv["paid_at"] = now_iso_ms()
    touch(inv)
    wo = DB.work_orders.get(inv["work_order_id"])
    if wo is not None:
        wo["billing_status"] = "PAID"
        if wo["execution_status"] == "COMPLETED":
            wo["execution_status"] = "CLOSED"
        touch(wo)
    return success_object(serialize_invoice(inv))
