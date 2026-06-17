"""WarrantyClaim endpoints + review/approve/deny state machine."""
from __future__ import annotations

import datetime

from flask import Blueprint, request

from db import db
from errors import (
    conflict,
    ERR_CLAIM_QTY_EXCEEDS_LINE,
    ERR_CLAIM_LINE_NOT_SHIPPED,
    ERR_CLAIM_NOT_SUBMITTED,
    ERR_CLAIM_NOT_OPEN,
    ERR_CLAIM_NOT_UNDER_REVIEW,
    ERR_WARRANTY_EXPIRED,
)
from middleware import require_role, get_body
from response import success, list_success
from services import common as c
from services.model import (
    stamp_common,
    touch,
    serialize,
    get_order_line,
    get_warranty_claim,
    get_part,
    get_sales_order,
    get_account,
)
from services.inventory import increment_on_hand, decrement_on_hand

bp = Blueprint("warranty_claims", __name__)

ALL_ROLES = ("CounterClerk", "WholesaleRep", "InventoryManager", "WarrantyAdmin")
RESOLUTIONS = {"REPLACE", "REFUND"}


@bp.post("/warranty-claims")
def create_warranty_claim():
    require_role("CounterClerk", "WholesaleRep", "WarrantyAdmin")
    body = get_body()
    order_line_id = c.as_nonempty_string(body, "order_line_id", required=True)
    qty = c.as_int(body, "qty", required=True, min_value=1)
    reason = c.as_string(body, "reason", required=True)
    resolution = c.as_enum(body, "resolution", RESOLUTIONS, required=False, default="REPLACE")
    restock_defective = c.as_bool(body, "restock_defective", required=False, default=False)

    line = get_order_line(order_line_id)

    # business: line must be SHIPPED
    if line["status"] != "SHIPPED":
        raise conflict(ERR_CLAIM_LINE_NOT_SHIPPED)
    # priority 12: qty must not exceed line qty
    if qty > line["qty"]:
        raise conflict(ERR_CLAIM_QTY_EXCEEDS_LINE)

    claim = {
        "order_line_id": order_line_id,
        "qty": qty,
        "reason": reason,
        "resolution": resolution,
        "credit_cents": 0,
        "restock_defective": restock_defective,
        "status": "SUBMITTED",
    }
    stamp_common(claim)
    db.warranty_claims[claim["id"]] = claim
    return success(serialize(claim), 201)


@bp.get("/warranty-claims")
def list_warranty_claims():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    order_line_id = request.args.get("order_line_id")
    status = request.args.get("status")
    filters = []
    if order_line_id is not None:
        filters.append(lambda w: w["order_line_id"] == order_line_id)
    if status is not None:
        filters.append(lambda w: w["status"] == status)
    page, total = c.paginate(db.warranty_claims.values(), limit, offset, filters)
    return list_success([serialize(w) for w in page], limit, offset, total)


@bp.get("/warranty-claims/<wid>")
def get_one_warranty_claim(wid):
    require_role(*ALL_ROLES)
    return success(serialize(get_warranty_claim(wid)))


@bp.post("/warranty-claims/<wid>/start-review")
def start_review(wid):
    require_role("WarrantyAdmin")
    claim = get_warranty_claim(wid)
    if claim["status"] != "SUBMITTED":
        raise conflict(ERR_CLAIM_NOT_SUBMITTED)
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return success(serialize(claim))


@bp.post("/warranty-claims/<wid>/deny")
def deny_claim(wid):
    require_role("WarrantyAdmin")
    claim = get_warranty_claim(wid)
    if claim["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise conflict(ERR_CLAIM_NOT_OPEN)
    claim["status"] = "DENIED"
    touch(claim)
    return success(serialize(claim))


@bp.post("/warranty-claims/<wid>/approve")
def approve_claim(wid):
    require_role("WarrantyAdmin")
    claim = get_warranty_claim(wid)
    # precondition: UNDER_REVIEW
    if claim["status"] != "UNDER_REVIEW":
        raise conflict(ERR_CLAIM_NOT_UNDER_REVIEW)

    line = get_order_line(claim["order_line_id"])
    part = get_part(line["part_id"])

    # warranty window: claim.created_at <= ship_time + warranty_days days.
    # Compared at full (microsecond) resolution captured at the moments of ship
    # and claim creation, so a same-millisecond claim on a 0-day window is still
    # correctly classified as expired (it is created strictly after ship).
    ship_dt = line.get("_shipped_at_us")
    claim_dt = claim.get("_created_us")
    if ship_dt is None or claim_dt is None:
        raise conflict(ERR_WARRANTY_EXPIRED)
    window_end = ship_dt + datetime.timedelta(days=part["warranty_days"])
    if claim_dt > window_end:
        raise conflict(ERR_WARRANTY_EXPIRED)

    # compute credit & apply remedy-specific effects
    if claim["resolution"] == "REFUND":
        credit = claim["qty"] * line["unit_merch_price_cents"]
        claim["credit_cents"] = credit
        order = get_sales_order(line["order_id"])
        account = get_account(order["account_id"])
        account["ar_balance_cents"] -= credit
        if account["ar_balance_cents"] < 0:
            account["ar_balance_cents"] = 0
        touch(account)
    else:  # REPLACE
        claim["credit_cents"] = 0
        # replacement unit issued: debit on_hand, may auto-suggest reorder
        decrement_on_hand(part, claim["qty"], suggest=True)

    # independent of resolution: restock defective unit if requested
    if claim["restock_defective"]:
        increment_on_hand(part, claim["qty"])

    claim["status"] = "APPROVED"
    touch(claim)
    return success(serialize(claim))
