"""OrderLine endpoints — line creation prices via the tier matrix."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import conflict, ERR_ORDER_NOT_OPEN, ERR_PART_DISCONTINUED
from middleware import require_role, get_body
from response import success, list_success
from services import common as c
from services.model import (
    stamp_common,
    touch,
    serialize,
    get_sales_order,
    get_part,
    get_price_tier,
    get_order_line,
    get_account,
)
from services.pricing import compute_line_pricing, recompute_order_rollup

bp = Blueprint("order_lines", __name__)

ALL_ROLES = ("CounterClerk", "WholesaleRep", "InventoryManager", "WarrantyAdmin")


@bp.post("/order-lines")
def create_order_line():
    require_role("CounterClerk", "WholesaleRep")
    body = get_body()
    order_id = c.as_nonempty_string(body, "order_id", required=True)
    part_id = c.as_nonempty_string(body, "part_id", required=True)
    qty = c.as_int(body, "qty", required=True, min_value=1)

    # existence (body, left-to-right): order before part
    order = get_sales_order(order_id)
    part = get_part(part_id)

    # priority 7: order must be OPEN
    if order["fulfillment_status"] != "OPEN":
        raise conflict(ERR_ORDER_NOT_OPEN)
    # priority 9: part must be ACTIVE
    if part["status"] != "ACTIVE":
        raise conflict(ERR_PART_DISCONTINUED)

    account = get_account(order["account_id"])
    tier = get_price_tier(account["price_tier_id"])

    # is_special_order: non-stockable, or requested qty exceeds available_qty now
    is_special = (not part["stockable"]) or (qty > part["available_qty"])

    pricing = compute_line_pricing(part, tier, account["account_type"], qty)

    line = {
        "order_id": order_id,
        "part_id": part_id,
        "price_tier_id": account["price_tier_id"],  # snapshot of account's tier
        "qty": qty,
        "is_special_order": is_special,
        "unit_merch_price_cents": pricing["unit_merch_price_cents"],
        "unit_core_price_cents": pricing["unit_core_price_cents"],
        "line_merch_total_cents": pricing["line_merch_total_cents"],
        "line_core_total_cents": pricing["line_core_total_cents"],
        "cores_outstanding": 0,
        "status": "PENDING",
    }
    stamp_common(line)
    db.order_lines[line["id"]] = line

    # adding a line mutates the parent order: recompute rollup & bump version
    lines = [ln for ln in db.order_lines.values() if ln["order_id"] == order_id]
    recompute_order_rollup(order, lines)
    touch(order)

    return success(serialize(line), 201)


@bp.get("/order-lines")
def list_order_lines():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    order_id = request.args.get("order_id")
    part_id = request.args.get("part_id")
    price_tier_id = request.args.get("price_tier_id")
    filters = []
    if order_id is not None:
        filters.append(lambda l: l["order_id"] == order_id)
    if part_id is not None:
        filters.append(lambda l: l["part_id"] == part_id)
    if price_tier_id is not None:
        filters.append(lambda l: l["price_tier_id"] == price_tier_id)
    page, total = c.paginate(db.order_lines.values(), limit, offset, filters)
    return list_success([serialize(l) for l in page], limit, offset, total)


@bp.get("/order-lines/<lid>")
def get_one_order_line(lid):
    require_role(*ALL_ROLES)
    return success(serialize(get_order_line(lid)))
