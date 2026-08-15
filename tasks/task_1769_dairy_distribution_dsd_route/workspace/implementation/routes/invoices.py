"""Invoice endpoints: get/list, payments (StoreReceiver), void (TerritoryManager)."""

from flask import Blueprint, request

from db import DB
from middleware import require_role, require_any, owner_check_store_receiver
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int,
    paginate, err, apply_changes,
)
from response import success_object, success_list
from errors import (
    ERR_INVOICE_NOT_FOUND, ERR_INVOICE_NOT_OPEN, ERR_INVOICE_NOT_VOIDABLE,
    ERR_PAYMENT_EXCEEDS_DUE,
)
from serializers import serialize_invoice
from services import recompute_invoice_status_and_order, refresh_store_open_ar

bp = Blueprint("invoices", __name__)


def get_invoice_or_404(invoice_id):
    inv = DB.invoices.get(invoice_id)
    if inv is None:
        raise err(ERR_INVOICE_NOT_FOUND, "Invoice id not found")
    return inv


@bp.get("/dairy/invoices/<invoiceId>")
def get_invoice(invoiceId):
    require_any()
    return success_object(serialize_invoice(get_invoice_or_404(invoiceId)))


@bp.get("/dairy/invoices")
def list_invoices():
    require_any()
    items = list(DB.invoices.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [i for i in items if i["order_id"] == order_id]
    store_id = request.args.get("store_id")
    if store_id is not None:
        items = [i for i in items if i["store_id"] == store_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda i: i["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_invoice(i) for i in page], limit, offset, total)


@bp.post("/dairy/invoices/<invoiceId>/payments")
def record_payment(invoiceId):
    user_id, _role = require_role("StoreReceiver")
    inv = get_invoice_or_404(invoiceId)
    owner_check_store_receiver(user_id, inv["store_id"])
    body = get_json_body()
    check_unknown_fields(body, {"amount_cents"})
    require_fields(body, ["amount_cents"])
    amount = opt_int(body, "amount_cents", gt=0)
    if inv["status"] != "OPEN":
        raise err(ERR_INVOICE_NOT_OPEN, "Payments require an OPEN invoice")
    # Fiscal checks run last on the priority ladder.
    if amount > inv["amount_due_cents"]:
        raise err(ERR_PAYMENT_EXCEEDS_DUE,
                  "Payment amount exceeds the invoice's amount due")
    inv["payments_applied_cents"] += amount
    recompute_invoice_status_and_order(inv)
    return success_object(serialize_invoice(inv), status=201)


@bp.post("/dairy/invoices/<invoiceId>/void")
def void_invoice(invoiceId):
    require_role("TerritoryManager")
    inv = get_invoice_or_404(invoiceId)
    if (inv["status"] != "OPEN" or inv["payments_applied_cents"] != 0
            or inv["credits_applied_cents"] != 0):
        raise err(ERR_INVOICE_NOT_VOIDABLE,
                  "Void requires an OPEN invoice with no payments and no credits")
    inv["status"] = "VOID"
    from util import touch
    touch(inv)
    order = DB.orders.get(inv["order_id"])
    if order is not None:
        apply_changes(order, {"payment_status": "UNINVOICED"})
    refresh_store_open_ar(inv["store_id"])
    return success_object(serialize_invoice(inv))
