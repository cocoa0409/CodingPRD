"""Payment endpoints: record / clear / bounce / refund / void."""

import json

from flask import Blueprint, Response

import db
import errors
import helpers
import middleware
import services
from helpers import (
    get_campaign, get_order, get_payment, new_id, now_iso,
    req_string, req_int, req_enum, opt_string,
    serialize_payment,
)
from middleware import get_body
from response import success_object

bp = Blueprint("payments", __name__)

METHODS = ("CASH", "CHECK", "CARD")


def _fingerprint(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _after_payment_change(order, seller):
    services.recompute_order_payment(order)
    services.recompute_seller_metrics(seller)
    services.evaluate_prizes_for_seller(seller)
    services.recompute_campaign_totals(db.campaigns[order["campaign_id"]])


@bp.post("/fundraiser/payments")
def record_payment():
    user_id, _role = middleware.require_role("Treasurer")
    body = get_body(required=True)
    # Schema (priority 4)
    order_id = req_string(body, "order_id")
    amount = req_int(body, "amount_cents", minimum=1)
    method = req_enum(body, "method", METHODS)
    external_ref = opt_string(body, "external_ref", default=None)
    idempotency_key = opt_string(body, "idempotency_key", default=None)

    # Idempotency replay (priority 5), scoped to endpoint+order
    scope = ("POST /fundraiser/payments", order_id)
    if idempotency_key is not None:
        record = db.idempotency_records.get((scope, idempotency_key))
        if record is not None:
            fp, status, body_json = record
            if fp != _fingerprint(body):
                raise errors.err_idempotency_conflict()
            return Response(body_json, status=status, content_type="application/json")

    # Body FK (priority 6)
    order = get_order(order_id)

    # State gate (priority 8)
    if order["status"] not in ("SUBMITTED", "LOCKED", "COMPLETED"):
        raise errors.err_invalid_state("Payments may only be recorded on SUBMITTED, LOCKED, or COMPLETED orders")

    # Money guard (priority 13): recorded + cleared coverage must not exceed total
    coverage = 0
    for p in db.payments.values():
        if p["order_id"] == order_id and p["status"] in ("RECORDED", "CLEARED"):
            coverage += p["amount_cents"] - p["refunded_amount_cents"]
    if coverage + amount > order["total_cents"]:
        raise errors.err_overpayment()

    pid = new_id()
    payment = {
        "id": pid,
        "order_id": order_id,
        "amount_cents": amount,
        "method": method,
        "external_ref": external_ref,
        "status": "RECORDED",
        "recorded_by_user_id": user_id,
        "refunded_amount_cents": 0,
        "idempotency_key": idempotency_key,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.payments[pid] = payment
    # Payment create re-derives order payment status (no cleared value change, but touch per spec).
    services.recompute_order_payment(order)

    resp, status = success_object(serialize_payment(payment), status=201)
    if idempotency_key is not None:
        db.idempotency_records[(scope, idempotency_key)] = (
            _fingerprint(body), status, resp.get_data(as_text=True),
        )
    return resp, status


@bp.post("/fundraiser/payments/<pid>/clear")
def clear_payment(pid):
    middleware.require_role("Treasurer")
    payment = get_payment(pid)
    get_body()
    if payment["status"] != "RECORDED":
        raise errors.err_invalid_state("Payment is not RECORDED")
    payment["status"] = "CLEARED"
    helpers.touch(payment)
    order = db.orders[payment["order_id"]]
    seller = db.sellers[order["seller_id"]]
    _after_payment_change(order, seller)
    return success_object(serialize_payment(payment))


@bp.post("/fundraiser/payments/<pid>/void")
def void_payment(pid):
    user_id, _role = middleware.require_role("Treasurer")
    payment = get_payment(pid)
    get_body()
    if payment["status"] != "RECORDED":
        raise errors.err_invalid_state("Payment is not RECORDED")
    if user_id != payment["recorded_by_user_id"]:
        raise errors.err_not_payment_recorder()
    payment["status"] = "VOIDED"
    helpers.touch(payment)
    order = db.orders[payment["order_id"]]
    services.recompute_order_payment(order)
    services.recompute_campaign_totals(db.campaigns[order["campaign_id"]])
    return success_object(serialize_payment(payment))


@bp.post("/fundraiser/payments/<pid>/bounce")
def bounce_payment(pid):
    middleware.require_role("Treasurer")
    payment = get_payment(pid)
    get_body()  # optional reason
    if payment["status"] != "CLEARED":
        raise errors.err_invalid_state("Payment is not CLEARED")
    if payment["method"] != "CHECK":
        raise errors.err_payment_method_not_bounceable()
    if payment["refunded_amount_cents"] != 0:
        raise errors.err_invalid_state("Payment has refunds and cannot bounce")
    order = db.orders[payment["order_id"]]
    campaign = db.campaigns[order["campaign_id"]]
    if campaign["status"] in ("CLOSED", "CANCELLED"):
        raise errors.err_invalid_state("Campaign is closed or cancelled")
    payment["status"] = "BOUNCED"
    helpers.touch(payment)
    services.post_ledger_entry(
        group_id=order["group_id"], campaign_id=order["campaign_id"],
        entry_type="BOUNCE_FEE_DEBIT", amount_cents=-services.BOUNCE_FEE_CENTS,
        reference_type="PAYMENT", reference_id=payment["id"],
        memo=f"Bounce fee for bounced payment {payment['id']}",
    )
    seller = db.sellers[order["seller_id"]]
    _after_payment_change(order, seller)
    return success_object(serialize_payment(payment))


@bp.post("/fundraiser/payments/<pid>/refund")
def refund_payment(pid):
    user_id, _role = middleware.require_role("Treasurer")
    payment = get_payment(pid)
    body = get_body(required=True)
    amount = req_int(body, "amount_cents", minimum=1)
    if payment["status"] != "CLEARED":
        raise errors.err_invalid_state("Payment is not CLEARED")
    order = db.orders[payment["order_id"]]
    if order["status"] == "CANCELLED":
        raise errors.err_invalid_state("Order is CANCELLED")
    if user_id == payment["recorded_by_user_id"]:
        raise errors.err_segregation("Refunding treasurer must differ from the recorder")
    remaining = payment["amount_cents"] - payment["refunded_amount_cents"]
    if amount > remaining:
        raise errors.err_refund_exceeds_cleared()
    payment["refunded_amount_cents"] += amount
    if payment["refunded_amount_cents"] == payment["amount_cents"]:
        payment["status"] = "REFUNDED"
    helpers.touch(payment)
    seller = db.sellers[order["seller_id"]]
    _after_payment_change(order, seller)
    return success_object(serialize_payment(payment))
