"""Standalone Payment endpoints: fetch, list, delete (unschedule), return (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import auth_required, ALL_ROLES, current_user_id
from response import ok_object, ok_array
from routes._helpers import (
    serialize, serialize_list, parse_pagination, paginate, order_by_created,
)
from services.common import touch
from services.ledger import recompute_batch_total
from services.audit import append_audit

bp = Blueprint("payments", __name__)


@bp.get("/ap/payments/<pid>")
def get_payment(pid):
    auth_required(ALL_ROLES)()
    p = db.payments.get(pid)
    if p is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment not found")
    return ok_object(serialize(p))


@bp.get("/ap/payments")
def list_payments():
    auth_required(ALL_ROLES)()
    limit, offset = parse_pagination()
    invoice_id = request.args.get("invoice_id")
    items = [p for p in db.payments.values()
             if invoice_id is None or p["invoice_id"] == invoice_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.delete("/ap/payments/<pid>")
def delete_payment(pid):
    auth_required({"APManager"})()
    p = db.payments.get(pid)
    if p is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment not found")
    batch = db.payment_batches.get(p["batch_id"])
    if batch is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment batch not found")
    # State: removable only from a BUILDING batch.
    if batch["status"] != "BUILDING":
        raise APIError(ERR_INVALID_STATE, 409, "Payment batch is not BUILDING")

    inv = db.invoices.get(p["invoice_id"])
    del db.payments[pid]
    # Invoice SCHEDULED -> APPROVED (revert).
    if inv is not None and inv["status"] == "SCHEDULED":
        inv["status"] = "APPROVED"
        touch(inv)
    recompute_batch_total(batch)
    touch(batch)  # bump version on remove (PRD §3.6)
    if inv is not None:
        append_audit(inv["id"], "UNSCHEDULED", current_user_id())
    return ok_object(serialize(p))


@bp.post("/ap/payments/<pid>/return")
def return_payment(pid):
    auth_required({"APManager"})()
    p = db.payments.get(pid)
    if p is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment not found")
    batch = db.payment_batches.get(p["batch_id"])
    if batch is None:
        raise APIError(ERR_NOT_FOUND, 404, "Payment batch not found")

    # State: return only when payment is SETTLED and parent batch is SETTLED.
    if p["settlement_status"] != "SETTLED" or batch["status"] != "SETTLED":
        raise APIError(ERR_INVALID_STATE, 409, "Payment is not in a returnable state")

    p["settlement_status"] = "RETURNED"
    touch(p)

    inv = db.invoices.get(p["invoice_id"])
    if inv is not None and inv["status"] == "PAID":
        inv["status"] = "APPROVED"
        touch(inv)

    # Subtract net from vendor 1099 YTD (conservation).
    if inv is not None:
        vendor = db.vendors.get(inv["vendor_id"])
        if vendor is not None:
            vendor["ytd_1099_paid_cents"] -= p["net_amount_cents"]
            touch(vendor)

    if inv is not None:
        append_audit(inv["id"], "PAYMENT_RETURNED", current_user_id())
    return ok_object(serialize(p))
