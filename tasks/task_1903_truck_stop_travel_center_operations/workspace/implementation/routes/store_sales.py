"""Store sales (PRD 3.6)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INSUFFICIENT_STOCK, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_MEMBER_NOT_ACTIVE, ERR_NOT_FOUND, ERR_SHIFT_NOT_OPEN,
)
from middleware import authorized, scope_member
from response import success_object
from routes.helpers import list_response, public
from services import loyalty
from services.core import (
    new_record, recompute_stock_low, touch, adjust_shift_expected,
)
from validate import (
    get_body, opt_str, query_filter, require_path_resource, valid_enum,
    valid_int,
)

bp = Blueprint("store_sales", __name__)

READ_ROLES = ["GeneralManager", "ShiftManager", "Cashier"]
SALE_STATUSES = ["COMPLETED", "REFUNDED"]


@bp.post("/sites/<sid>/store-sales")
def create_store_sale(sid):
    authorized(["Cashier"])
    require_path_resource("sites", sid)
    body = get_body()

    # p6: body FK existence
    shift = None
    if body.get("shift_id") is not None:
        shift = db["shifts"].get(body["shift_id"]) if isinstance(body.get("shift_id"), str) else None
        if shift is None:
            raise_error(ERR_NOT_FOUND, "shift_id does not resolve")
    member = None
    if body.get("loyalty_member_id") is not None:
        member = db["loyalty_members"].get(body["loyalty_member_id"]) \
            if isinstance(body.get("loyalty_member_id"), str) else None
        if member is None:
            raise_error(ERR_NOT_FOUND, "loyalty_member_id does not resolve")
    lines_raw = body.get("lines")
    resolved = []
    if isinstance(lines_raw, list):
        for ln in lines_raw:
            if isinstance(ln, dict) and ln.get("stock_item_id") is not None:
                item = db["stock_items"].get(ln["stock_item_id"]) \
                    if isinstance(ln.get("stock_item_id"), str) else None
                if item is None:
                    raise_error(ERR_NOT_FOUND, "stock_item_id does not resolve")
                resolved.append((item, ln.get("quantity")))

    # p9: the attribution shift must be OPEN
    if shift is not None and shift["status"] != "OPEN":
        raise_error(ERR_SHIFT_NOT_OPEN, "attribution shift is not OPEN")
    # p14: accrual requires an ACTIVE member
    if member is not None and member["status"] != "ACTIVE":
        raise_error(ERR_MEMBER_NOT_ACTIVE, "loyalty member is not ACTIVE")
    # p32: stock sufficiency per line (aggregated per item), never negative
    requested = {}
    for item, qty in resolved:
        if valid_int(qty) and qty > 0:
            requested[item["id"]] = requested.get(item["id"], 0) + qty
            if requested[item["id"]] > item["on_hand_quantity"]:
                raise_error(ERR_INSUFFICIENT_STOCK,
                            f"quantity exceeds on-hand stock for {item['sku']}")

    # p41: final shape validation
    if shift is None:
        raise_error(ERR_INVALID_REQUEST, "shift_id is required")
    tender = body.get("tender_type")
    if not valid_enum(tender, ["CASH", "CARD"]):
        raise_error(ERR_INVALID_REQUEST, "tender_type must be CASH or CARD")
    if not isinstance(lines_raw, list) or not lines_raw:
        raise_error(ERR_INVALID_REQUEST, "lines must be a non-empty array")
    for ln in lines_raw:
        if not isinstance(ln, dict) or ln.get("stock_item_id") is None:
            raise_error(ERR_INVALID_REQUEST, "each line requires stock_item_id")
        qty = ln.get("quantity")
        if not valid_int(qty) or qty <= 0:
            raise_error(ERR_INVALID_REQUEST, "line quantity must be a positive integer")

    lines = [{"stock_item_id": item["id"], "quantity": qty,
              "unit_price_cents": item["unit_price_cents"]}
             for item, qty in resolved]
    subtotal = sum(ln["quantity"] * ln["unit_price_cents"] for ln in lines)
    # Decrement stock (atomicity: sufficiency was validated for all lines above)
    for item_id, qty in requested.items():
        item = db["stock_items"][item_id]
        item["on_hand_quantity"] -= qty
        recompute_stock_low(item)
        touch(item)
    rec = new_record("store_sales", {
        "site_id": sid,
        "shift_id": shift["id"],
        "loyalty_member_id": member["id"] if member else None,
        "lines": lines,
        "subtotal_cents": subtotal,
        "total_cents": subtotal,
        "tender_type": tender,
        "status": "COMPLETED",
        "payment_status": "PAID",
        "points_earned": 0,
    })
    earned = loyalty.earn_points_for(member, rec["total_cents"], "STORE_SALE", rec["id"])
    rec["points_earned"] = earned
    if tender == "CASH":
        adjust_shift_expected(shift, rec["total_cents"])
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/store-sales")
def list_store_sales(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {"site_id": sid, "status": query_filter("status", SALE_STATUSES)}
    return list_response("store_sales", filters)


@bp.get("/store-sales/<rid>")
def get_store_sale(rid):
    caller = authorized(READ_ROLES + ["LoyaltyMember"])
    rec = require_path_resource("store_sales", rid)
    scope_member(caller, rec["loyalty_member_id"])
    return success_object(public(rec))


@bp.post("/store-sales/<rid>/refund")
def refund_store_sale(rid):
    authorized(["ShiftManager"])
    sale = require_path_resource("store_sales", rid)
    body = get_body()
    opt_str(body, "reason")
    if sale["status"] != "COMPLETED":
        raise_error(ERR_INVALID_STATE, "store sale is not COMPLETED")
    sale["status"] = "REFUNDED"
    sale["payment_status"] = "REFUNDED"
    for ln in sale["lines"]:
        item = db["stock_items"].get(ln["stock_item_id"])
        if item is not None:
            item["on_hand_quantity"] += ln["quantity"]
            recompute_stock_low(item)
            touch(item)
    if sale.get("points_earned") and sale["loyalty_member_id"]:
        loyalty.clawback_newest(sale["loyalty_member_id"], sale["points_earned"],
                                "ADJUSTMENT", sale["id"])
    if sale["tender_type"] == "CASH":
        shift = db["shifts"].get(sale["shift_id"])
        if shift is not None:
            adjust_shift_expected(shift, -sale["total_cents"])
    touch(sale)
    return success_object(public(sale))
