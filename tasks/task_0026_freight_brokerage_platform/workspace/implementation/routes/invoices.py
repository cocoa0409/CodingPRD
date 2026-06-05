"""Invoice endpoints (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_PAYMENT_OVERAGE,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page, sort_default
from services.validation import (
    require_fields,
    require_int_or_str_int,
    lookup_path_or_404,
)
from services.calculations import recompute_shipper_open_ar


bp = Blueprint("invoices", __name__)


def _shipper_id_for_invoice(invoice):
    load = db.loads.get(invoice.get("load_id"))
    if load is None:
        return None
    q = db.quote_requests.get(load.get("quote_request_id"))
    return q.get("shipper_id") if q else None


def _carrier_id_for_invoice(invoice):
    load = db.loads.get(invoice.get("load_id"))
    return load.get("carrier_id") if load else None


def _invoice_visible_to(invoice, role: str, uid: str) -> bool:
    if role == "BrokerOps":
        return True
    if role == "Shipper":
        return _shipper_id_for_invoice(invoice) == uid
    if role == "Carrier":
        return _carrier_id_for_invoice(invoice) == uid
    return False


@bp.get("/freight/invoices/<iid>")
def get_invoice(iid: str):
    require_auth(["BrokerOps", "Shipper", "Carrier"])()
    inv = lookup_path_or_404(db.invoices, iid, "Invoice")
    if not _invoice_visible_to(inv, current_role(), current_user_id()):
        raise APIError(ERR_UNAUTHORIZED, 403, "Not permitted to view this invoice")
    return ok_object(inv, 200)


@bp.get("/freight/invoices")
def list_invoices():
    require_auth(["BrokerOps", "Shipper", "Carrier"])()
    limit, offset = paginate_params(request.args)
    load_filter = request.args.get("load_id")
    status_filter = request.args.get("status")
    items = list(db.invoices.values())
    role = current_role()
    uid = current_user_id()
    if role == "Shipper":
        items = [i for i in items if _shipper_id_for_invoice(i) == uid]
    elif role == "Carrier":
        items = [i for i in items if _carrier_id_for_invoice(i) == uid]
    if load_filter:
        items = [i for i in items if i.get("load_id") == load_filter]
    if status_filter:
        items = [i for i in items if i.get("status") == status_filter]
    items = sort_default(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/freight/invoices/<iid>/payments")
def post_payment(iid: str):
    require_auth(["BrokerOps"])()
    inv = lookup_path_or_404(db.invoices, iid, "Invoice")
    body = get_json_body()
    require_fields(body, ["amount_cents"])
    amount = require_int_or_str_int(body["amount_cents"], "amount_cents")

    # priority 5: only ISSUED/PARTIALLY_PAID accept payments.
    if inv.get("status") not in {"ISSUED", "PARTIALLY_PAID"}:
        raise APIError(ERR_INVALID_STATE, 409, "Invoice does not accept payments")

    # priority 18: amount > 0 and amount_paid + amount <= total.
    if amount <= 0:
        raise APIError(ERR_PAYMENT_OVERAGE, 422, "amount_cents must be > 0")
    current_paid = int(inv.get("amount_paid_cents", 0))
    total = int(inv["total_cents"])
    if current_paid + amount > total:
        raise APIError(ERR_PAYMENT_OVERAGE, 422, "Payment exceeds invoice balance")

    new_paid = current_paid + amount
    inv["amount_paid_cents"] = new_paid
    if new_paid == total:
        inv["status"] = "PAID"
    else:
        inv["status"] = "PARTIALLY_PAID"
    db.bump(inv)

    # Cascade: open AR recompute; load CLOSED on full payment.
    load = db.loads.get(inv.get("load_id"))
    if load is not None:
        q = db.quote_requests.get(load.get("quote_request_id"))
        if q is not None:
            recompute_shipper_open_ar(q.get("shipper_id"))
        if inv["status"] == "PAID" and load.get("status") == "INVOICED":
            load["status"] = "CLOSED"
            db.bump(load)
    return ok_object(inv, 200)
