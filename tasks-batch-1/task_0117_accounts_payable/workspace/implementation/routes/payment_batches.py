"""PaymentBatch + Payment endpoints (PRD §3.6, §3.7).

Batch lifecycle: BUILDING -> RELEASED -> SETTLED, with RELEASED -> VOID.
Adding/removing a payment bumps the batch version and recomputes the total.
Release is OCC-guarded (expected_paymentbatch_version) and enforces segregation
of duties. Settle bubbles payment settlement and recomputes vendor 1099 YTD.
"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_PAYMENT_METHOD_MISMATCH, ERR_VENDOR_ON_HOLD, ERR_INVOICE_ALREADY_SCHEDULED,
    ERR_SEGREGATION_OF_DUTIES, ERR_BATCH_EMPTY, ERR_STALE_BATCH_VERSION,
)
from middleware import auth_required, ALL_ROLES, current_user_id
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_fields, serialize, serialize_list, is_int, is_str,
    parse_pagination, paginate, order_by_created,
)
from services.calculations import early_pay_discount
from services.common import new_common_fields, touch
from services.ledger import recompute_batch_total, recompute_po_matched
from services.audit import append_audit

bp = Blueprint("payment_batches", __name__)

PAYMENT_METHODS = {"ACH", "CHECK", "CARD"}


def _parse_date(value: str):
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise APIError(ERR_INVALID_REQUEST, 400, "run_date must be an ISO 8601 date")


def _batch_members(bid):
    return [p for p in db.payments.values() if p["batch_id"] == bid]


@bp.post("/ap/payment-batches")
def create_batch():
    auth_required({"APManager"})()
    body = get_body()
    require_fields(body, ["payment_method", "run_date"])

    if body["payment_method"] not in PAYMENT_METHODS:
        raise APIError(ERR_INVALID_REQUEST, 400, "payment_method must be one of ACH, CHECK, CARD")
    run_date = body["run_date"]
    if not is_str(run_date):
        raise APIError(ERR_INVALID_REQUEST, 400, "run_date must be a string")
    _parse_date(run_date)

    batch = {
        **new_common_fields(),
        "payment_method": body["payment_method"],
        "run_date": run_date,
        "total_disbursed_cents": 0,
        "status": "BUILDING",
        "released_by": None,
    }
    db.payment_batches[batch["id"]] = batch
    return ok_object(serialize(batch), http_status=201)


@bp.get("/ap/payment-batches/<bid>")
def get_batch(bid):
    auth_required(ALL_ROLES)()
    batch = db.payment_batches.get(bid)
    if batch is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment batch not found")
    return ok_object(serialize(batch))


@bp.post("/ap/payment-batches/<bid>/payments")
def add_payment(bid):
    auth_required({"APManager"})()
    batch = db.payment_batches.get(bid)
    if batch is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment batch not found")

    body = get_body()
    require_fields(body, ["invoice_id"])
    invoice_id = body["invoice_id"]
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise APIError(ERR_NOT_FOUND, 404, "Invoice not found")

    # State: batch must be BUILDING and invoice must be APPROVED.
    if batch["status"] != "BUILDING":
        raise APIError(ERR_INVALID_STATE, 409, "Payment batch is not BUILDING")
    if inv["status"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, 409, "Invoice is not APPROVED")

    vendor = db.vendors.get(inv["vendor_id"])
    if vendor is None:
        raise APIError(ERR_NOT_FOUND, 404, "Vendor not found")

    # business (priority order from scaffold): method mismatch (422) ->
    # vendor on hold (409) -> already scheduled (409).
    if vendor["payment_method"] != batch["payment_method"]:
        raise APIError(ERR_PAYMENT_METHOD_MISMATCH, 422,
                       "Invoice vendor's payment_method differs from the batch")
    if vendor["status"] == "ON_HOLD":
        raise APIError(ERR_VENDOR_ON_HOLD, 409, "Vendor is ON_HOLD")
    # No double-pay: invoice may be in at most one payment across non-VOID batches.
    for p in db.payments.values():
        if p["invoice_id"] != invoice_id:
            continue
        other_batch = db.payment_batches.get(p["batch_id"])
        if other_batch is not None and other_batch["status"] != "VOID":
            raise APIError(ERR_INVOICE_ALREADY_SCHEDULED, 409,
                           "Invoice already has a payment in a non-VOID batch")

    gross = inv["total_amount_cents"]
    if inv["discount_deadline"]:
        discount = early_pay_discount(
            inv["total_amount_cents"], _parse_date(inv["discount_deadline"]),
            _parse_date(batch["run_date"]), vendor["early_pay_terms_pct"],
        )
    else:
        discount = 0
    net = gross - discount

    payment = {
        **new_common_fields(),
        "batch_id": bid,
        "invoice_id": invoice_id,
        "gross_amount_cents": gross,
        "discount_taken_cents": discount,
        "net_amount_cents": net,
        "settlement_status": "PENDING",
    }
    db.payments[payment["id"]] = payment

    # Invoice APPROVED -> SCHEDULED.
    inv["status"] = "SCHEDULED"
    touch(inv)
    recompute_batch_total(batch)
    touch(batch)  # bump version on add (PRD §3.6)
    append_audit(invoice_id, "SCHEDULED", current_user_id())
    return ok_object(serialize(payment), http_status=201)


@bp.get("/ap/payment-batches/<bid>/payments")
def list_batch_payments(bid):
    auth_required(ALL_ROLES)()
    if bid not in db.payment_batches:
        raise APIError(ERR_NOT_FOUND, 404, "Payment batch not found")
    limit, offset = parse_pagination()
    items = _batch_members(bid)
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.post("/ap/payment-batches/<bid>/release")
def release_batch(bid):
    auth_required({"APManager"})()
    batch = db.payment_batches.get(bid)
    if batch is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment batch not found")

    body = get_body()
    require_fields(body, ["expected_paymentbatch_version"])
    expected = body["expected_paymentbatch_version"]
    if not is_int(expected):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_paymentbatch_version must be an integer")

    # State: only a BUILDING batch may be released.
    if batch["status"] != "BUILDING":
        raise APIError(ERR_INVALID_STATE, 409, "Payment batch is not BUILDING")

    members = _batch_members(bid)
    actor = current_user_id()

    # Business priority (scaffold): segregation (403) < empty (409) < OCC (412)
    # by priority number, but PRD §3.6 lists OCC first, then empty, then SoD.
    # Follow PRD prose order: version -> non-empty -> segregation of duties.
    if expected != batch["version"]:
        raise APIError(ERR_STALE_BATCH_VERSION, 412, "expected_paymentbatch_version is stale")
    if len(members) == 0:
        raise APIError(ERR_BATCH_EMPTY, 409, "Cannot release a batch with zero payments")
    for p in members:
        inv = db.invoices.get(p["invoice_id"])
        if inv is None:
            continue
        if actor == inv.get("coded_by") or actor == inv.get("approved_by"):
            raise APIError(ERR_SEGREGATION_OF_DUTIES, 403,
                           "Releaser coded or approved a member invoice")

    batch["released_by"] = actor
    batch["status"] = "RELEASED"
    # total_disbursed_cents is already current (frozen at this value on release).
    touch(batch)  # increments version by 1 (PRD §3.6)

    # Bubble-up: each member invoice SCHEDULED -> PAID.
    for p in members:
        inv = db.invoices.get(p["invoice_id"])
        if inv is not None and inv["status"] == "SCHEDULED":
            inv["status"] = "PAID"
            touch(inv)
            append_audit(inv["id"], "PAID", actor)

    return ok_object(serialize(batch))


@bp.post("/ap/payment-batches/<bid>/settle")
def settle_batch(bid):
    auth_required({"APManager"})()
    batch = db.payment_batches.get(bid)
    if batch is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment batch not found")
    if batch["status"] != "RELEASED":
        raise APIError(ERR_INVALID_STATE, 409, "Payment batch is not RELEASED")

    for p in _batch_members(bid):
        if p["settlement_status"] == "PENDING":
            p["settlement_status"] = "SETTLED"
            touch(p)
            vendor = db.vendors.get(db.invoices[p["invoice_id"]]["vendor_id"]) \
                if p["invoice_id"] in db.invoices else None
            if vendor is not None:
                vendor["ytd_1099_paid_cents"] += p["net_amount_cents"]
                touch(vendor)

    batch["status"] = "SETTLED"
    touch(batch)
    return ok_object(serialize(batch))


@bp.post("/ap/payment-batches/<bid>/void")
def void_batch(bid):
    auth_required({"APManager"})()
    batch = db.payment_batches.get(bid)
    if batch is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment batch not found")
    if batch["status"] != "RELEASED":
        raise APIError(ERR_INVALID_STATE, 409, "Payment batch is not RELEASED")

    actor = current_user_id()
    for p in list(_batch_members(bid)):
        inv = db.invoices.get(p["invoice_id"])
        if inv is not None and inv["status"] == "PAID":
            inv["status"] = "APPROVED"
            touch(inv)
            append_audit(inv["id"], "PAYMENT_VOIDED", actor)
        del db.payments[p["id"]]

    batch["total_disbursed_cents"] = 0
    batch["status"] = "VOID"
    touch(batch)
    return ok_object(serialize(batch))
