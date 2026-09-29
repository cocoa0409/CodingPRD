"""Invoices and the append-only payment attempts (PRD 3.5 / 3.6)."""
from flask import Blueprint, request

import config
import lookup
import middleware
import serializers
import validation as v
from clock import clock, parse_date
from db import db
from errors import fail
from middleware import auth
from response import listing, object_response
from services import dunning
from services.derive import invoice_attempts, max_payment_attempts

bp = Blueprint("invoices", __name__)


@bp.post("/invoices/<invoice_id>/payment-attempts")
@auth(config.ROLE_OPS)
def create_payment_attempt(invoice_id):
    data = v.body()
    outcome = v.get_enum(data, "outcome", config.PAYMENT_OUTCOMES, required=True)
    amount_cents = v.get_int(data, "amount_cents", required=True)
    decline_code = v.get_string(data, "decline_code", min_len=1, max_len=40)

    invoice = lookup.invoice(invoice_id)
    sub = db.subscriptions.get(invoice["subscription_id"])
    plan = db.offer_plans.get(sub["offer_plan_id"]) if sub else None
    reader = db.readers.get(sub["reader_id"]) if sub else None

    attempt_no = len(invoice_attempts(invoice["id"])) + 1
    if sub["dunning_status"] == "FAILED_FINAL" or attempt_no > max_payment_attempts(sub):
        fail("ERR_DUNNING_EXHAUSTED")
    if invoice["status"] not in ("OPEN", "PAST_DUE"):
        fail("ERR_INVOICE_NOT_PAYABLE")
    next_retry_on = sub.get("next_retry_on")
    if next_retry_on is not None and clock.date() < parse_date(next_retry_on):
        fail("ERR_RETRY_TOO_EARLY")
    if amount_cents != invoice["total_cents"]:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH")

    attempt = dunning.record_attempt(
        invoice, sub, plan, reader, outcome, amount_cents, decline_code
    )
    return object_response(serializers.payment_attempt(attempt), 201)


@bp.get("/invoices/<invoice_id>")
@auth(config.ROLE_OPS, config.ROLE_COMPLIANCE, config.ROLE_READER)
def read_invoice(invoice_id):
    middleware.guard_invoice(invoice_id)
    return object_response(serializers.invoice(lookup.invoice(invoice_id)))


@bp.get("/invoices/<invoice_id>/payment-attempts")
@auth(config.ROLE_OPS, config.ROLE_COMPLIANCE)
def list_payment_attempts(invoice_id):
    lookup.invoice(invoice_id)
    rows = sorted(invoice_attempts(invoice_id), key=lambda a: (a["attempt_no"], a["_seq"]))
    outcome = request.args.get("outcome")
    if outcome:
        rows = [r for r in rows if r["outcome"] == outcome]
    return listing(rows, serializers.payment_attempt)
