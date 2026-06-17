"""SalesOrder endpoints + fulfillment & settlement state machines."""
from __future__ import annotations

import datetime

from flask import Blueprint, request

from db import db, now_iso
from errors import (
    conflict,
    APIError,
    ERR_CHANNEL_ACCOUNT_MISMATCH,
    ERR_EMPTY_ORDER,
    ERR_ACCOUNT_ON_HOLD,
    ERR_INSUFFICIENT_STOCK,
    ERR_STALE_VERSION,
    ERR_INVALID_FULFILLMENT_STATE,
    ERR_SPECIAL_ORDER_NOT_READY,
    ERR_ORDER_ALREADY_INVOICED,
    ERR_NOT_SHIPPED,
    ERR_ALREADY_INVOICED,
    ERR_NOT_INVOICED,
    ERR_CREDIT_LIMIT_EXCEEDED,
)
from middleware import require_role, get_body
from response import success, list_success
from services import common as c
from services.model import (
    stamp_common,
    touch,
    serialize,
    get_account,
    get_sales_order,
)
from services.inventory import recompute_available, maybe_auto_suggest_reorder
from services.pricing import recompute_order_rollup, compute_hotshot_fee

bp = Blueprint("sales_orders", __name__)

ALL_ROLES = ("CounterClerk", "WholesaleRep", "InventoryManager", "WarrantyAdmin")
CHANNELS = {"COUNTER", "WHOLESALE"}


def order_lines_for(order_id: str) -> list:
    return [ln for ln in db.order_lines.values() if ln["order_id"] == order_id]


@bp.post("/sales-orders")
def create_sales_order():
    require_role("CounterClerk", "WholesaleRep")
    body = get_body()
    account_id = c.as_nonempty_string(body, "account_id", required=True)
    channel = c.as_enum(body, "channel", CHANNELS, required=True)
    hotshot_requested = c.as_bool(body, "hotshot_requested", required=False, default=False)
    account = get_account(account_id)

    # priority 6: channel must match account type
    expected_channel = "COUNTER" if account["account_type"] == "RETAIL" else "WHOLESALE"
    if channel != expected_channel:
        raise conflict(ERR_CHANNEL_ACCOUNT_MISMATCH)

    order = {
        "account_id": account_id,
        "channel": channel,
        "fulfillment_status": "OPEN",
        "settlement_status": "UNBILLED",
        "merchandise_subtotal_cents": 0,
        "core_subtotal_cents": 0,
        "order_total_cents": 0,
        "hotshot_requested": hotshot_requested,
        "hotshot_fee_cents": 0,
    }
    stamp_common(order)
    db.sales_orders[order["id"]] = order
    return success(serialize(order), 201)


@bp.get("/sales-orders")
def list_sales_orders():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    account_id = request.args.get("account_id")
    fulfillment_status = request.args.get("fulfillment_status")
    settlement_status = request.args.get("settlement_status")
    filters = []
    if account_id is not None:
        filters.append(lambda o: o["account_id"] == account_id)
    if fulfillment_status is not None:
        filters.append(lambda o: o["fulfillment_status"] == fulfillment_status)
    if settlement_status is not None:
        filters.append(lambda o: o["settlement_status"] == settlement_status)
    page, total = c.paginate(db.sales_orders.values(), limit, offset, filters)
    return list_success([serialize(o) for o in page], limit, offset, total)


@bp.get("/sales-orders/<oid>")
def get_one_sales_order(oid):
    require_role(*ALL_ROLES)
    return success(serialize(get_sales_order(oid)))


@bp.post("/sales-orders/<oid>/allocate")
def allocate_order(oid):
    require_role("CounterClerk", "WholesaleRep")
    order = get_sales_order(oid)
    body = get_body()
    expected_version = c.as_int(body, "expected_sales_order_version", required=True)

    lines = order_lines_for(oid)

    # business preconditions (PRD §3.4), in narrative order then OCC last (per §2.9
    # the version check is the final precondition listed for allocate).
    # fulfillment must be OPEN to allocate
    if order["fulfillment_status"] != "OPEN":
        raise conflict(ERR_INVALID_FULFILLMENT_STATE)
    # at least one line
    if len(lines) == 0:
        raise conflict(ERR_EMPTY_ORDER)
    # account must be ACTIVE
    account = get_account(order["account_id"])
    if account["status"] != "ACTIVE":
        raise conflict(ERR_ACCOUNT_ON_HOLD)
    # every non-special line must have sufficient available stock
    for ln in lines:
        if ln["status"] == "CANCELLED":
            continue
        if ln["is_special_order"]:
            continue
        part = db.parts[ln["part_id"]]
        if part["available_qty"] < ln["qty"]:
            raise conflict(ERR_INSUFFICIENT_STOCK)
    # OCC: expected version must match
    if expected_version != order["version"]:
        raise APIError(ERR_STALE_VERSION, 412)

    # side effects: reserve stock for non-special lines
    for ln in lines:
        if ln["status"] == "CANCELLED":
            continue
        if ln["is_special_order"]:
            # special-order lines stay PENDING with no reservation
            continue
        part = db.parts[ln["part_id"]]
        part["reserved_qty"] += ln["qty"]
        recompute_available(part)
        touch(part)
        ln["status"] = "ALLOCATED"
        touch(ln)

    # compute hotshot fee, recompute rollup including it
    order["hotshot_fee_cents"] = compute_hotshot_fee(order, lines)
    recompute_order_rollup(order, lines)
    order["fulfillment_status"] = "ALLOCATED"
    touch(order)
    return success(serialize(order))


@bp.post("/sales-orders/<oid>/ship")
def ship_order(oid):
    require_role("CounterClerk", "WholesaleRep")
    order = get_sales_order(oid)
    body = get_body()
    expected_version = c.as_int(body, "expected_sales_order_version", required=True)

    lines = order_lines_for(oid)

    # precondition: must be ALLOCATED
    if order["fulfillment_status"] != "ALLOCATED":
        raise conflict(ERR_INVALID_FULFILLMENT_STATE)
    # precondition: no special-order line still PENDING without received stock
    for ln in lines:
        if ln["status"] == "CANCELLED":
            continue
        if ln["is_special_order"] and ln["status"] == "PENDING":
            part = db.parts[ln["part_id"]]
            if part["available_qty"] < ln["qty"]:
                raise conflict(ERR_SPECIAL_ORDER_NOT_READY)
    # OCC
    if expected_version != order["version"]:
        raise APIError(ERR_STALE_VERSION, 412)

    # side effects: for ALLOCATED lines deduct on_hand & release reservation.
    # Special-order PENDING lines that now have stock are also fulfilled.
    affected_parts = []
    for ln in lines:
        if ln["status"] == "ALLOCATED":
            part = db.parts[ln["part_id"]]
            part["on_hand_qty"] -= ln["qty"]
            if part["on_hand_qty"] < 0:
                part["on_hand_qty"] = 0
            part["reserved_qty"] -= ln["qty"]
            if part["reserved_qty"] < 0:
                part["reserved_qty"] = 0
            recompute_available(part)
            touch(part)
            if part["id"] not in [p["id"] for p in affected_parts]:
                affected_parts.append(part)
            if part["is_rebuildable"]:
                ln["cores_outstanding"] = ln["qty"]
            ln["status"] = "SHIPPED"
            ln["_shipped_at_us"] = datetime.datetime.now(datetime.timezone.utc)
            touch(ln)
        elif ln["is_special_order"] and ln["status"] == "PENDING":
            part = db.parts[ln["part_id"]]
            part["on_hand_qty"] -= ln["qty"]
            if part["on_hand_qty"] < 0:
                part["on_hand_qty"] = 0
            recompute_available(part)
            touch(part)
            if part["id"] not in [p["id"] for p in affected_parts]:
                affected_parts.append(part)
            if part["is_rebuildable"]:
                ln["cores_outstanding"] = ln["qty"]
            ln["status"] = "SHIPPED"
            ln["_shipped_at_us"] = datetime.datetime.now(datetime.timezone.utc)
            touch(ln)

    # cascade hop 2: low-stock reorder auto-suggest per affected part
    for part in affected_parts:
        maybe_auto_suggest_reorder(part)

    order["fulfillment_status"] = "SHIPPED"
    touch(order)
    return success(serialize(order))


@bp.post("/sales-orders/<oid>/cancel")
def cancel_order(oid):
    require_role("CounterClerk", "WholesaleRep")
    order = get_sales_order(oid)
    lines = order_lines_for(oid)

    # precondition: fulfillment OPEN or ALLOCATED
    if order["fulfillment_status"] not in ("OPEN", "ALLOCATED"):
        raise conflict(ERR_INVALID_FULFILLMENT_STATE)
    # precondition: settlement must be UNBILLED
    if order["settlement_status"] != "UNBILLED":
        raise conflict(ERR_ORDER_ALREADY_INVOICED)

    if order["fulfillment_status"] == "ALLOCATED":
        # compensation: release reservations for allocated lines
        for ln in lines:
            if ln["status"] == "ALLOCATED":
                part = db.parts[ln["part_id"]]
                part["reserved_qty"] -= ln["qty"]
                if part["reserved_qty"] < 0:
                    part["reserved_qty"] = 0
                recompute_available(part)
                touch(part)

    for ln in lines:
        if ln["status"] != "CANCELLED":
            ln["status"] = "CANCELLED"
            touch(ln)

    recompute_order_rollup(order, lines)
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return success(serialize(order))


@bp.post("/sales-orders/<oid>/invoice")
def invoice_order(oid):
    require_role("CounterClerk", "WholesaleRep")
    order = get_sales_order(oid)

    # precondition: fulfillment SHIPPED
    if order["fulfillment_status"] != "SHIPPED":
        raise conflict(ERR_NOT_SHIPPED)
    # precondition: settlement UNBILLED
    if order["settlement_status"] != "UNBILLED":
        raise conflict(ERR_ALREADY_INVOICED)

    account = get_account(order["account_id"])
    # credit discipline for WHOLESALE
    if account["account_type"] == "WHOLESALE":
        if account["ar_balance_cents"] + order["order_total_cents"] > account["credit_limit_cents"]:
            raise APIError(ERR_CREDIT_LIMIT_EXCEEDED, 402)

    account["ar_balance_cents"] += order["order_total_cents"]
    touch(account)
    order["settlement_status"] = "INVOICED"
    touch(order)
    return success(serialize(order))


@bp.post("/sales-orders/<oid>/pay")
def pay_order(oid):
    require_role("CounterClerk", "WholesaleRep")
    order = get_sales_order(oid)

    if order["settlement_status"] != "INVOICED":
        raise conflict(ERR_NOT_INVOICED)

    account = get_account(order["account_id"])
    account["ar_balance_cents"] -= order["order_total_cents"]
    if account["ar_balance_cents"] < 0:
        account["ar_balance_cents"] = 0
    touch(account)
    order["settlement_status"] = "PAID"
    touch(order)
    return success(serialize(order))
