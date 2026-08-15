"""Invoice routes (PRD 3.8). Payment is exact; the amount check outranks the
already-paid check when both would fail (PRD 2.10 rung 15)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import body_json, ctx, list_response, require_role
from response import ok
from services.credit import refresh_standing

bp = Blueprint("invoices", __name__)


@bp.get("/api/invoices")
def list_invoices():
    return list_response(
        store.invoices.values(),
        [("carrier_id", "carrier_id"), ("status", "status")],
    )


@bp.get("/api/invoices/<invoiceId>")
def get_invoice(invoiceId):
    ctx()
    inv = store.invoices.get(invoiceId)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", 404, "invoice id does not exist")
    return ok(db.public(inv), 200)


@bp.post("/api/invoices/<invoiceId>/record-payment")
def record_payment(invoiceId):
    _uid, role = ctx()
    require_role(role, ("FinanceAdmin",))
    inv = store.invoices.get(invoiceId)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", 404, "invoice id does not exist")
    body = body_json()
    amount = body.get("amount_cents")
    # Rung 12: field must be an integer
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents must be an integer")
    # Rung 15 (pinned order): exact amount first, then payable state
    if amount != inv["amount_due_cents"]:
        raise ApiError(
            "ERR_PAYMENT_AMOUNT_MISMATCH",
            400,
            "amount_cents must equal amount_due_cents exactly",
        )
    if inv["status"] not in ("ISSUED", "PAST_DUE"):
        raise ApiError(
            "ERR_INVOICE_NOT_PAYABLE", 409, "invoice is already PAID"
        )
    inv["status"] = "PAID"
    db.bump(inv)
    carrier = store.carriers.get(inv["carrier_id"])
    if carrier is not None:
        refresh_standing(carrier)
    return ok(db.public(inv), 200)
