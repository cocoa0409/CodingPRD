"""Payments: deposit, balance capture (OCC-guarded, credit waterfall), list."""
from flask import Blueprint, request, g

import clock
import serializers as S
import validators as V
from db import store
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_STALE_ORDER_VERSION, ERR_PROOF_NOT_APPROVED, ERR_INSUFFICIENT_CREDIT,
)
from middleware import require_auth
from response import success, list_response, parse_pagination
from services import calculations as calc
from services.orders import get_order_or_404, assert_owner

bp = Blueprint("payments", __name__)


@bp.route("/orders/<oid>/payments", methods=["POST"])
@require_auth(["Customer"])
def record_payment(oid):
    order = get_order_or_404(oid)
    assert_owner(order)

    data = V.body()
    kind = V.require_enum(data, "kind", {"DEPOSIT", "BALANCE", "REFUND"})

    # This endpoint settles the DEPOSIT leg (UNPAID -> DEPOSIT_PAID).
    # state precondition: production_status QUOTED and payment_status UNPAID.
    if order["payment_status"] != "UNPAID":
        raise err(ERR_INVALID_STATE, "deposit only valid while UNPAID")
    if order["production_status"] != "QUOTED":
        raise err(ERR_INVALID_STATE, "deposit only valid while QUOTED")

    # wrong-leg or no positive deposit due -> amount mismatch
    if kind != "DEPOSIT" or order["deposit_due_cents"] <= 0:
        raise err(ERR_PAYMENT_AMOUNT_MISMATCH, "deposit amount mismatch")

    payment = {
        "order_id": oid,
        "kind": "DEPOSIT",
        "amount_cents": order["deposit_due_cents"],
        "credit_applied_cents": 0,
        "settled_at": clock.iso_millis(),
    }
    store.stamp_create(payment, common_fields=False)
    store.payments[payment["id"]] = payment

    # PRD 3.2: lifetime_spend_cents accumulates the cents of captured payments
    # across all of the customer's orders. The deposit is a captured payment, so
    # it accrues to lifetime spend (and re-tiers loyalty) at deposit time.
    customer = store.customers[order["customer_id"]]
    customer["lifetime_spend_cents"] += order["deposit_due_cents"]
    customer["loyalty_tier"] = calc.loyalty_tier(customer["lifetime_spend_cents"])
    store.touch(customer)

    order["payment_status"] = "DEPOSIT_PAID"
    store.touch(order)
    return success(S.payment(payment), status=201)


@bp.route("/orders/<oid>/balance-payment", methods=["POST"])
@require_auth(["Customer"])
def balance_payment(oid):
    order = get_order_or_404(oid)
    assert_owner(order)

    data = V.body()
    kind = V.require_enum(data, "kind", {"DEPOSIT", "BALANCE", "REFUND"})
    expected_version = V.require_int(data, "expected_order_version")
    applied_credit = V.optional_int(data, "applied_credit_cents", default=0, minimum=0)

    # state precondition (priority 6): payment_status DEPOSIT_PAID.
    if order["payment_status"] != "DEPOSIT_PAID":
        raise err(ERR_INVALID_STATE, "balance only valid while DEPOSIT_PAID")

    # OCC (priority 7) before business rules.
    if expected_version != order["version"]:
        raise err(ERR_STALE_ORDER_VERSION, "stale order version")

    # proof gate (priority 13): must be PROOF_APPROVED.
    if order["production_status"] != "PROOF_APPROVED":
        raise err(ERR_PROOF_NOT_APPROVED, "proof must be approved before balance")

    gross_balance = order["balance_due_cents"]

    # credit sufficiency (priority 15)
    if applied_credit > 0:
        customer = store.customers[order["customer_id"]]
        if applied_credit > customer["store_credit_cents"] or applied_credit > gross_balance:
            raise err(ERR_INSUFFICIENT_CREDIT, "applied credit exceeds available or balance")

    # payment-amount correctness (priority 16): wrong leg, or nothing due.
    if kind != "BALANCE" or gross_balance <= 0:
        raise err(ERR_PAYMENT_AMOUNT_MISMATCH, "balance amount mismatch")

    customer = store.customers[order["customer_id"]]
    credit_applied, fresh_tender = calc.compute_balance_capture(
        gross_balance, applied_credit, customer["store_credit_cents"]
    )

    payment = {
        "order_id": oid,
        "kind": "BALANCE",
        "amount_cents": fresh_tender,
        "credit_applied_cents": credit_applied,
        "settled_at": clock.iso_millis(),
    }
    store.stamp_create(payment, common_fields=False)
    store.payments[payment["id"]] = payment

    # reconcile customer: spend credit, accrue fresh tender to lifetime, re-tier.
    customer["store_credit_cents"] -= credit_applied
    customer["lifetime_spend_cents"] += fresh_tender
    customer["loyalty_tier"] = calc.loyalty_tier(customer["lifetime_spend_cents"])
    store.touch(customer)

    order["applied_credit_cents"] = applied_credit
    order["balance_due_cents"] = 0
    order["payment_status"] = "PAID_IN_FULL"
    store.touch(order)
    return success(S.payment(payment), status=201)


@bp.route("/orders/<oid>/payments", methods=["GET"])
@require_auth(["Customer", "BakeryStaff", "BakeryManager"])
def list_payments(oid):
    order = get_order_or_404(oid)
    assert_owner(order)
    limit, offset = parse_pagination(request.args)
    items = [p for p in store.payments.values() if p["order_id"] == oid]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    return list_response([S.payment(p) for p in items], limit, offset)
