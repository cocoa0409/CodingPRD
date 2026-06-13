"""Dispute / deduction endpoints (PRD §3.4)."""
from flask import Blueprint

import db
from errors import (
    err, ERR_INVALID_STATE, ERR_DISPUTE_EXCEEDS_BALANCE, ERR_VALIDATION,
)
from middleware import get_identity, authorize
from response import success, list_response
from services import domain, lookup
from services.common import (
    stamp_create, touch, get_json_body, require_str, require_int, require_enum,
    parse_pagination, paginate,
)

bp = Blueprint("disputes", __name__)

REASON_CODES = {"PRICING", "SHORTAGE", "DAMAGE", "DUPLICATE", "QUALITY"}


def _recompute_customer_of_invoice(invoice, recompute_stage=False):
    customer = db.customers.get(invoice["customer_id"])
    if customer is not None:
        domain.recompute_customer(customer, recompute_stage=recompute_stage)


@bp.route("/ar/disputes", methods=["POST"])
def create_dispute():
    _, role = get_identity()
    authorize(role, ["COLLECTIONS_AGENT", "AR_MANAGER"])
    body = get_json_body()
    invoice_id = require_str(body, "invoice_id")
    invoice = lookup.get_invoice(invoice_id)
    amount = require_int(body, "amount_cents", minimum=1)
    reason = require_enum(body, "reason_code", REASON_CODES)

    # ceiling (priority 11): amount must not exceed invoice dunnable balance.
    dun = domain.dunnable(invoice)
    if amount > dun:
        raise err(ERR_DISPUTE_EXCEEDS_BALANCE, "dispute exceeds invoice dunnable balance")

    d = {
        "invoice_id": invoice_id,
        "amount_cents": amount,
        "reason_code": reason,
        "status": "OPEN",
        "resolution_credit_cents": 0,
        "reopen_count": 0,
    }
    stamp_create(d)
    db.disputes[d["id"]] = d

    # set invoice.disputed_amount_cents (accumulate the new disputed amount)
    invoice["disputed_amount_cents"] = invoice["disputed_amount_cents"] + amount
    # if dispute covers the entire balance -> DISPUTED (from OPEN or PARTIAL)
    if invoice["disputed_amount_cents"] == invoice["balance_cents"] and \
            invoice["status"] in ("OPEN", "PARTIAL"):
        was_open = invoice["status"] == "OPEN"
        invoice["status"] = "DISPUTED"
        if was_open:
            invoice["dunning_stage_index"] = 0
    touch(invoice)

    _recompute_customer_of_invoice(invoice, recompute_stage=True)
    return success(domain.serialize_dispute(d), status=201)


@bp.route("/ar/disputes/<did>", methods=["GET"])
def get_dispute(did):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "COLLECTIONS_AGENT", "AUDITOR"])
    d = lookup.get_dispute(did)
    return success(domain.serialize_dispute(d), status=200)


@bp.route("/ar/disputes/<did>/start-review", methods=["POST"])
def start_review(did):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER"])
    d = lookup.get_dispute(did)
    if d["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "dispute not OPEN")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success(domain.serialize_dispute(d), status=200)


@bp.route("/ar/disputes/<did>/resolve", methods=["POST"])
def resolve(did):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER"])
    d = lookup.get_dispute(did)
    body = get_json_body()
    credit = require_int(body, "resolve_credit_cents", minimum=0)
    if d["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "dispute not UNDER_REVIEW")
    if credit > d["amount_cents"]:
        raise err(ERR_VALIDATION, "resolve_credit_cents exceeds dispute amount")

    invoice = lookup.get_invoice(d["invoice_id"])
    d["status"] = "RESOLVED_CREDIT"
    d["resolution_credit_cents"] = credit
    touch(d)

    # decrement invoice balance by the credit; clear disputed amount for this dispute
    invoice["balance_cents"] = invoice["balance_cents"] - credit
    invoice["disputed_amount_cents"] = max(
        0, invoice["disputed_amount_cents"] - d["amount_cents"]
    )
    if invoice["balance_cents"] == 0:
        invoice["status"] = "PAID"
    elif invoice["status"] == "DISPUTED":
        # restore to OPEN/PARTIAL depending on whether anything has been paid
        if invoice["balance_cents"] < invoice["face_amount_cents"]:
            invoice["status"] = "PARTIAL"
        else:
            invoice["status"] = "OPEN"
    touch(invoice)

    _recompute_customer_of_invoice(invoice, recompute_stage=True)
    return success(domain.serialize_dispute(d), status=200)


@bp.route("/ar/disputes/<did>/reject", methods=["POST"])
def reject(did):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER"])
    d = lookup.get_dispute(did)
    if d["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "dispute not UNDER_REVIEW")
    invoice = lookup.get_invoice(d["invoice_id"])
    d["status"] = "REJECTED"
    touch(d)
    _clear_dispute_from_invoice(invoice, d)
    _recompute_customer_of_invoice(invoice, recompute_stage=True)
    return success(domain.serialize_dispute(d), status=200)


@bp.route("/ar/disputes/<did>/reopen", methods=["POST"])
def reopen(did):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER"])
    d = lookup.get_dispute(did)
    if d["status"] not in ("RESOLVED_CREDIT", "REJECTED"):
        raise err(ERR_INVALID_STATE, "dispute not reopenable")
    invoice = lookup.get_invoice(d["invoice_id"])
    if invoice["status"] in ("PAID", "WRITTEN_OFF"):
        raise err(ERR_INVALID_STATE, "invoice is terminal")
    d["status"] = "UNDER_REVIEW"
    d["reopen_count"] = d["reopen_count"] + 1
    d["resolution_credit_cents"] = 0
    touch(d)
    # re-apply the disputed amount
    invoice["disputed_amount_cents"] = invoice["disputed_amount_cents"] + d["amount_cents"]
    if invoice["disputed_amount_cents"] == invoice["balance_cents"] and \
            invoice["status"] in ("OPEN", "PARTIAL"):
        invoice["status"] = "DISPUTED"
    touch(invoice)
    _recompute_customer_of_invoice(invoice, recompute_stage=True)
    return success(domain.serialize_dispute(d), status=200)


@bp.route("/ar/disputes/<did>/withdraw", methods=["POST"])
def withdraw(did):
    _, role = get_identity()
    authorize(role, ["COLLECTIONS_AGENT"])
    d = lookup.get_dispute(did)
    if d["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise err(ERR_INVALID_STATE, "dispute not withdrawable")
    invoice = lookup.get_invoice(d["invoice_id"])
    d["status"] = "WITHDRAWN"
    touch(d)
    _clear_dispute_from_invoice(invoice, d)
    _recompute_customer_of_invoice(invoice, recompute_stage=True)
    return success(domain.serialize_dispute(d), status=200)


def _clear_dispute_from_invoice(invoice, dispute):
    """Remove this dispute's disputed amount and restore the invoice's dunnable
    balance. A dispute that had covered the full balance returns DISPUTED->OPEN
    (or PARTIAL if partially paid)."""
    invoice["disputed_amount_cents"] = max(
        0, invoice["disputed_amount_cents"] - dispute["amount_cents"]
    )
    if invoice["status"] == "DISPUTED":
        if invoice["balance_cents"] < invoice["face_amount_cents"]:
            invoice["status"] = "PARTIAL"
        else:
            invoice["status"] = "OPEN"
    touch(invoice)
