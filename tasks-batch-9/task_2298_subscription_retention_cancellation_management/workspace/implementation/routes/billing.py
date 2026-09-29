"""Invoices, dunning attempts and the payment simulator (PRD §3.4, §3.7)."""
from flask import Blueprint

import constants as K
import serializers as S
import validation as V
from db import store
from errors import fail
from middleware import auth
from response import created, ok
from routes import send_list
from services import ops

bp = Blueprint("billing", __name__)


@bp.get("/invoices/<invoice_id>")
@auth()
def read_invoice(invoice_id):
    return ok(S.invoice(V.must_exist("invoices", invoice_id)))


@bp.get("/invoices")
@auth()
def list_invoices():
    return send_list(store.invoices.values(), S.invoice,
                     {"subscription_id": "subscription_id",
                      "payment_method_id": "payment_method_id", "status": "status"})


@bp.post("/invoices/<invoice_id>/dunning-attempts")
@auth("BillingOperator")
def create_attempt(invoice_id):
    invoice = V.must_exist("invoices", invoice_id)
    if invoice["status"] not in ("OPEN", "FAILED"):
        fail("ERR_INVOICE_NOT_PAYABLE", "The invoice is no longer payable.")
    attempt = ops.schedule_dunning_attempt(invoice)
    return created(S.dunning_attempt(attempt))


@bp.get("/dunning-attempts/<attempt_id>")
@auth()
def read_attempt(attempt_id):
    return ok(S.dunning_attempt(V.must_exist("dunning_attempts", attempt_id)))


@bp.get("/dunning-attempts")
@auth()
def list_attempts():
    return send_list(store.dunning_attempts.values(), S.dunning_attempt,
                     {"invoice_id": "invoice_id",
                      "previous_attempt_id": "previous_attempt_id", "outcome": "outcome"})


@bp.post("/_payments/simulate")
@auth("PlatformAdmin", "BillingOperator")
def simulate_payment():
    data = V.body()
    invoice = V.fk(data, "invoice_id", "invoices")
    V.req_str(data, "invoice_id")
    outcome = V.req_enum(data, "outcome", K.SETTLE_OUTCOMES)
    decline_code = V.opt_enum(data, "decline_code", K.DECLINE_CODES)

    if invoice["status"] not in ("OPEN", "FAILED"):
        fail("ERR_INVOICE_NOT_PAYABLE", "The invoice is no longer payable.")
    attempt = ops.settle_payment(invoice, outcome, decline_code)
    return ok(S.dunning_attempt(attempt))
