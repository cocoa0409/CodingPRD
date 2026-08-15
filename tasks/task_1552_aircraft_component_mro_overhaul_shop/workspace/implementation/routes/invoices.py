from flask import Blueprint, request

from db import store, now_iso
from errors import ApiError
from helpers import get_invoice_or_404, list_response, pub, touch
from middleware import ALL_ROLES, get_json_body, require_roles, validate_body
from response import ok

bp = Blueprint("invoices", __name__, url_prefix="/mro")


@bp.route("/invoices/<invoiceId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_invoice(invoiceId):
    return ok(pub(get_invoice_or_404(invoiceId)))


@bp.route("/invoices", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_invoices():
    return list_response(
        store.invoices.values(),
        filters={
            "work_order_id": "work_order_id",
            "lease_agreement_id": "lease_agreement_id",
            "exchange_agreement_id": "exchange_agreement_id",
            "customer_id": "customer_id",
            "status": "status",
        },
    )


@bp.route("/invoices/<invoiceId>/pay", methods=["POST"])
@require_roles("Customer")
def pay_invoice(invoiceId):
    inv = get_invoice_or_404(invoiceId)
    body = validate_body(get_json_body(), {"amount_cents": ("int", True)})
    # Order: from-state, then ownership, then exact amount.
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_INVALID_STATE", 409, "Invoice not in ISSUED")
    if request.user_id != inv["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the billed customer")
    if body["amount_cents"] != inv["total_cents"]:
        raise ApiError(
            "ERR_PAYMENT_AMOUNT_MISMATCH", 422, "Payment amount must equal invoice total"
        )
    inv["status"] = "PAID"
    inv["paid_at"] = now_iso()
    touch(inv)
    cust = store.customers.get(inv["customer_id"])
    if cust is not None:
        cust["current_exposure_cents"] -= inv["total_cents"]
        touch(cust)
    return ok(pub(inv))
