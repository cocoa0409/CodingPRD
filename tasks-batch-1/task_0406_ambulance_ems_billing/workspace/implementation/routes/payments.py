"""Payment endpoints: post (PATIENT direct / PAYER), list, fetch (PRD §3.9)."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_INVALID_ENUM,
    ERR_INVALID_REQUEST,
    ERR_PAYMENT_EXCEEDS_BALANCE,
    err,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_json_body,
    get_or_404,
    init_common,
    paginate,
    parse_pagination,
    require_fields,
    resolve_fk,
)
from services.ledger import advance_billing_dimension, reconcile_transport_ledger
from services.serialize import serialize, serialize_list

bp = Blueprint("payments", __name__)

PAYMENT_SOURCES = {"PAYER", "PATIENT"}


@bp.route("/transports/<transport_id>/payments", methods=["POST"])
def post_payment(transport_id):
    principal = authenticate()
    require_role(principal, ["Biller"])
    transport = get_or_404(store.transports, transport_id)
    body = get_json_body()

    # priority 4: body FK (claim_id when present)
    if body.get("claim_id") is not None:
        resolve_fk(store.claims, body["claim_id"])

    # priority 5: required fields
    require_fields(body, ["source", "amount_cents"])
    # priority 6: enum
    source = body["source"]
    if source not in PAYMENT_SOURCES:
        raise err(ERR_INVALID_ENUM, "Invalid payment source")

    amount = body["amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise err(ERR_INVALID_REQUEST, "amount_cents must be an integer")
    if amount <= 0:
        raise err(ERR_INVALID_REQUEST, "amount_cents must be greater than zero")

    # priority 21: patient payment may not overpay the patient balance
    if source == "PATIENT" and amount > transport["patient_responsibility_cents"]:
        raise err(ERR_PAYMENT_EXCEEDS_BALANCE, "Patient payment exceeds current balance")

    payment = {
        "transport_id": transport_id,
        "claim_id": body.get("claim_id"),
        "source": source,
        "amount_cents": amount,
        "posted_iso": None,
    }
    init_common(payment)
    payment["posted_iso"] = payment["created_at"]
    store.payments[payment["id"]] = payment

    reconcile_transport_ledger(transport)
    advance_billing_dimension(transport)

    return success(serialize(payment), 201)


@bp.route("/transports/<transport_id>/payments", methods=["GET"])
def list_transport_payments(transport_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Biller", "ComplianceOfficer"])
    get_or_404(store.transports, transport_id)
    limit, offset = parse_pagination()
    claim_id = request.args.get("claim_id")
    items = [p for p in store.payments.values() if p["transport_id"] == transport_id]
    if claim_id is not None:
        items = [p for p in items if p.get("claim_id") == claim_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)


@bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Biller", "ComplianceOfficer"])
    rec = get_or_404(store.payments, payment_id)
    return success(serialize(rec), 200)


@bp.route("/payments", methods=["GET"])
def list_payments():
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Biller", "ComplianceOfficer"])
    limit, offset = parse_pagination()
    claim_id = request.args.get("claim_id")
    transport_id = request.args.get("transport_id")
    items = list(store.payments.values())
    if claim_id is not None:
        items = [p for p in items if p.get("claim_id") == claim_id]
    if transport_id is not None:
        items = [p for p in items if p["transport_id"] == transport_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)
