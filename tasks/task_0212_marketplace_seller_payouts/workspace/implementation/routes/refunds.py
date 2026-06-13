"""Refund endpoints (PRD §3.6 proportional clawback)."""
from decimal import Decimal

from flask import Blueprint, request

from common import (
    parse_pagination, paginate, sort_by_created, get_json_body,
    require_fields, require_enum, require_int, round_half_up, err,
)
from errors import (
    ERR_INVALID_STATE, ERR_REFUND_EXCEEDS_REMAINING, ERR_ORDER_ALREADY_CLAWED,
)
from db import db
from middleware import (
    get_identity, require_roles, ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE,
)
from response import success
from routes.helpers import fetch, ensure_seller_owns
from services.entity import stamp_create, touch
from services.order import final_net
from services.ledger import (
    post_ledger_entry, HOLD_AVAILABLE, HOLD_REVERSED,
)
from services.seller import refresh_seller_derived

bp = Blueprint("refunds", __name__)

REASONS = {"BUYER_REMORSE", "NOT_AS_DESCRIBED", "DAMAGED", "NOT_RECEIVED"}


@bp.post("/refunds")
def create_refund():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_SELLER])
    body = get_json_body()
    require_fields(body, ["order_id", "refund_amount_cents", "reason"])
    require_int(body["refund_amount_cents"], "refund_amount_cents", 1)
    require_enum(body["reason"], REASONS, "reason")
    order = fetch(db.orders, body["order_id"])
    ensure_seller_owns(role, user_id, order["seller_id"])

    refund = {
        "order_id": order["id"],
        "seller_id": order["seller_id"],
        "refund_amount_cents": body["refund_amount_cents"],
        "reason": body["reason"],
        "refund_status": "REQUESTED",
        "commission_returned_cents": 0,
        "clawback_cents": 0,
    }
    stamp_create(refund)
    db.refunds[refund["id"]] = refund
    return success(refund, status=201)


@bp.get("/refunds/<refund_id>")
def get_refund(refund_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    refund = fetch(db.refunds, refund_id)
    ensure_seller_owns(role, user_id, refund["seller_id"])
    return success(refund)


@bp.get("/refunds")
def list_refunds():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    limit, offset = parse_pagination()
    items = list(db.refunds.values())
    if role == ROLE_SELLER:
        items = [r for r in items if r["seller_id"] == user_id]
    for key in ("order_id", "seller_id", "refund_status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)


@bp.post("/refunds/<refund_id>/apply")
def apply_refund(refund_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    refund = fetch(db.refunds, refund_id)
    order = fetch(db.orders, refund["order_id"])
    seller = db.sellers[order["seller_id"]]

    # State guard: refund must be REQUESTED (PRD §3.6).
    if refund["refund_status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Only a REQUESTED refund can be applied.")
    # Order settlement must be PENDING or AVAILABLE.
    if order["settlement_status"] not in ("PENDING", "AVAILABLE"):
        raise err(ERR_INVALID_STATE,
                  "Order settlement must be PENDING or AVAILABLE to refund.")
    # Business: refund ceiling precedes already-clawed guard (PRD §2.11 order:
    # priority 10 ERR_REFUND_EXCEEDS_REMAINING before priority 11
    # ERR_ORDER_ALREADY_CLAWED).
    remaining = order["gross_amount_cents"] - order["refunded_amount_cents"]
    if refund["refund_amount_cents"] > remaining:
        raise err(ERR_REFUND_EXCEEDS_REMAINING,
                  "Refund exceeds the order's remaining unrefunded gross.")
    if order["clawback_status"] != "NONE":
        raise err(ERR_ORDER_ALREADY_CLAWED, "Order has already been clawed.")

    schedule = db.fee_schedules[order["fee_schedule_id"]]
    refund_amount = refund["refund_amount_cents"]
    commission_returned = round_half_up(
        Decimal(refund_amount) * Decimal(schedule["commission_bps"]) / Decimal(10000)
    )
    clawback = refund_amount - commission_returned
    refund["commission_returned_cents"] = commission_returned
    refund["clawback_cents"] = clawback

    # "if the refund is full, the order's original ORDER_PROCEEDS entry is marked
    # REVERSED" (PRD §3.6). Full = refund covers the whole gross. (An order can
    # be clawed at most once, so refunded_amount_cents is 0 here.)
    full_refund = refund_amount == order["gross_amount_cents"]

    # Post REFUND_CLAWBACK ledger entry for the negative clawback amount, in the
    # same hold_state bucket as the order's current proceeds so balances net.
    proceeds_state = _order_proceeds_state(order)
    post_ledger_entry(
        seller_id=order["seller_id"],
        source_type="REFUND_CLAWBACK",
        source_id=order["id"],
        amount_cents=-clawback,
        hold_state=proceeds_state,
        memo="Refund clawback",
    )
    if full_refund:
        _mark_proceeds_reversed(order)

    order["clawback_status"] = "REFUND_CLAWED"
    order["refunded_amount_cents"] += refund_amount
    order["net_earnings_cents"] = final_net(order, schedule)
    touch(order)

    refund["refund_status"] = "APPLIED"
    touch(refund)

    refresh_seller_derived(seller)
    return success(refund)


def _order_proceeds_state(order):
    """Return the hold_state the order's proceeds currently occupy: AVAILABLE if
    matured, PENDING otherwise. The clawback debit lands in the same bucket so
    it offsets the original credit (PRD §2.6)."""
    return HOLD_AVAILABLE if order["settlement_status"] == "AVAILABLE" else "PENDING"


def _mark_proceeds_reversed(order):
    """Flip the order's original ORDER_PROCEEDS entry hold_state to REVERSED
    (PRD §2.4, §3.6 full refund)."""
    for e in db.ledger_entries.values():
        if (e["source_type"] == "ORDER_PROCEEDS" and e["source_id"] == order["id"]
                and e["hold_state"] != HOLD_REVERSED):
            e["hold_state"] = HOLD_REVERSED


@bp.post("/refunds/<refund_id>/void")
def void_refund(refund_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    refund = fetch(db.refunds, refund_id)
    if refund["refund_status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Only a REQUESTED refund can be voided.")
    refund["refund_status"] = "VOIDED"
    touch(refund)
    return success(refund)
