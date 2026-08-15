"""Invoice endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize
from errors import ERR_INVOICE_NOT_FOUND, ERR_INVALID_REQUEST, raise_err
from serializers import invoice_out
from services import invoice_service
from util import body_json, get_or_404, req_int, req_date, opt_str, success_object

bp = Blueprint("invoices", __name__)


@bp.route("/feedlot/invoices/<invoice_id>/payments", methods=["POST"])
def apply_payment(invoice_id):
    _, role = authenticate()
    authorize(role, ["BillingClerk"])
    body = body_json()

    amount_cents = req_int(body, "amount_cents")
    payment_date = req_date(body, "payment_date")

    if amount_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be > 0")

    rec = get_or_404(store.invoices, invoice_id, ERR_INVOICE_NOT_FOUND, "Invoice")

    invoice_service.apply_payment(rec, amount_cents, payment_date)
    return success_object(invoice_out(rec))


@bp.route("/feedlot/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    _, role = authenticate()
    authorize(role, ["BillingClerk"])
    body = body_json()

    reason = opt_str(body, "reason")

    rec = get_or_404(store.invoices, invoice_id, ERR_INVOICE_NOT_FOUND, "Invoice")

    invoice_service.void_invoice(rec, reason)
    return success_object(invoice_out(rec))
