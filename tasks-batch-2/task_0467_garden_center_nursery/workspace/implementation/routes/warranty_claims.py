"""WarrantyClaim endpoints: file, read, approve, deny + list."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from clock import clock
from db import db, base_versioned, touch, now_iso
from errors import err
from lookups import body, get_order_line, get_claim
from middleware import require_roles, parse_pagination, paginate
from response import ok, created, ok_list
from services import calc
from services.loyalty import append_event
from validation import req_int_gt, opt_enum

bp = Blueprint("warranty_claims", __name__)

RESOLUTIONS = {"REPLACEMENT", "REFUND"}


def claim_view(c):
    return {
        "id": c["id"],
        "order_line_id": c["order_line_id"],
        "nursery_id": c["nursery_id"],
        "claim_qty": c["claim_qty"],
        "filed_at": c["filed_at"],
        "resolution": c["resolution"],
        "payout_cents": c["payout_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _within_warranty(order, product):
    """True if clock.now <= fulfilled_at + warranty_days."""
    fulfilled_at = order.get("_fulfilled_at")
    if fulfilled_at is None:
        return False
    deadline = fulfilled_at + timedelta(days=product["warranty_days"])
    return clock.get() <= deadline


@bp.post("/order-lines/<line_id>/warranty-claims")
@require_roles("SalesClerk")
def file_claim(line_id):
    line = get_order_line(line_id)
    data = body()
    claim_qty = req_int_gt(data, "claim_qty", 0)
    resolution = opt_enum(data, "resolution", RESOLUTIONS, "REPLACEMENT")

    order = db.orders[line["order_id"]]
    product = db.products[line["product_id"]]

    # claim_qty <= line.qty (priority 10)
    if claim_qty > line["qty"]:
        err(errors.ERR_CLAIM_QTY_EXCEEDS_LINE, "claim_qty exceeds line qty")

    # warranty offered (priority 10)
    if product["warranty_days"] <= 0:
        err(errors.ERR_WARRANTY_NOT_OFFERED, "product offers no warranty")

    # within warranty window from order FULFILLED time (priority 10)
    if not _within_warranty(order, product):
        err(errors.ERR_WARRANTY_EXPIRED, "warranty window expired")

    c = base_versioned()
    c.update({
        "order_line_id": line_id,
        "nursery_id": order["nursery_id"],
        "claim_qty": claim_qty,
        "filed_at": now_iso(),
        "resolution": resolution,
        "payout_cents": 0,
        "status": "FILED",
    })
    db.warranty_claims[c["id"]] = c
    return created(claim_view(c))


@bp.get("/order-lines/<line_id>/warranty-claims")
@require_roles("SalesClerk", "InventoryManager")
def list_line_claims(line_id):
    get_order_line(line_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [c for c in db.warranty_claims.values()
             if c["order_line_id"] == line_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([claim_view(c) for c in page], limit, offset, total)


@bp.get("/warranty-claims/<claim_id>")
@require_roles("SalesClerk", "InventoryManager")
def read_claim(claim_id):
    c = get_claim(claim_id)
    return ok(claim_view(c))


@bp.post("/warranty-claims/<claim_id>/approve")
@require_roles("SalesClerk")
def approve_claim(claim_id):
    c = get_claim(claim_id)
    if c["status"] != "FILED":
        err(errors.ERR_CLAIM_NOT_FILED, "claim not FILED")

    line = db.order_lines[c["order_line_id"]]
    order = db.orders[line["order_id"]]
    product = db.products[line["product_id"]]

    # still within window measured from order fulfillment (priority 10)
    if not _within_warranty(order, product):
        err(errors.ERR_WARRANTY_EXPIRED, "warranty window expired")

    if c["resolution"] == "REFUND":
        payout = calc.warranty_payout(
            line["line_net_cents"], line["qty"], c["claim_qty"], product["warranty_pct"])
        c["payout_cents"] = payout
        # loyalty claw-back: -(floor(payout/100) * loyalty_accrual_per_dollar)
        account = db.accounts[order["account_id"]]
        nursery = db.nurseries[order["nursery_id"]]
        refunded_dollars = payout // 100
        clawback = refunded_dollars * nursery["loyalty_accrual_per_dollar"]
        if clawback > 0:
            append_event(account, "REVERSAL", -clawback, "WARRANTY_CLAIM", c["id"])
    else:
        c["payout_cents"] = 0

    c["status"] = "APPROVED"
    touch(c)
    return ok(claim_view(c))


@bp.post("/warranty-claims/<claim_id>/deny")
@require_roles("SalesClerk")
def deny_claim(claim_id):
    c = get_claim(claim_id)
    if c["status"] != "FILED":
        err(errors.ERR_CLAIM_NOT_FILED, "claim not FILED")
    c["status"] = "DENIED"
    touch(c)
    return ok(claim_view(c))
