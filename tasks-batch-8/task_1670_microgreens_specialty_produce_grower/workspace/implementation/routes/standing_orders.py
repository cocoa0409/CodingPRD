"""StandingOrder and OrderItem endpoints (PRD 3.5)."""
from flask import Blueprint, g, request

from db import db
from errors import (
    ApiError,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_EMPTY_ORDER,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ORDER_ITEM_NOT_FOUND,
    ERR_ORDER_NOT_EDITABLE,
    ERR_STALE_VERSION,
    ERR_STANDING_ORDER_NOT_FOUND,
    ERR_VARIETY_NOT_LISTED,
    ERR_VARIETY_NOT_FOUND,
    ERR_WEEKLY_CHANGE_LOCKED,
)
from middleware import (
    get_body,
    opt_int,
    req_int,
    req_num,
    req_str,
    require_roles,
)
from response import success, serialize
from services import (
    line_extension_cents,
    new_resource,
    q3,
    recompute_subtotal,
    touch,
)
from routes.listing import list_response

bp = Blueprint("standing_orders", __name__)

ALL = ("Grower", "Chef", "OpsManager")


def _get_order(oid):
    rec = db.standing_orders.get(oid)
    if rec is None:
        raise ApiError(
            404, ERR_STANDING_ORDER_NOT_FOUND, "standing order id does not exist."
        )
    return rec


def _check_chef_ownership(order):
    """Chef identity is entity-backed by Customer (PRD 2.1)."""
    if g.user_role == "Chef" and order["customer_id"] != g.user_id:
        raise ApiError(
            403, ERR_FORBIDDEN, "Chef may only act on their own customer's orders."
        )


@bp.post("/standing-orders")
@require_roles("Chef")
def create_standing_order():
    body = get_body()
    customer_id = req_str(body, "customer_id")
    effective_week_start = req_str(body, "effective_week_start")
    change_cutoff_day = req_int(body, "change_cutoff_day")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise ApiError(404, ERR_CUSTOMER_NOT_FOUND, "customer_id does not exist.")
    if customer_id != g.user_id:
        raise ApiError(
            403, ERR_FORBIDDEN, "Chef may only open orders for their own customer."
        )
    if change_cutoff_day < 0 or change_cutoff_day > 6:
        raise ApiError(
            400, ERR_INVALID_REQUEST, "change_cutoff_day must be in [0, 6]."
        )
    rec = new_resource(
        {
            "customer_id": customer_id,
            "effective_week_start": effective_week_start,
            "change_cutoff_day": change_cutoff_day,
            "status": "DRAFT",
            "weekly_subtotal_cents": 0,
        }
    )
    db.standing_orders[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/standing-orders")
@require_roles(*ALL)
def list_standing_orders():
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    records = list(db.standing_orders.values())
    if customer_id is not None:
        records = [r for r in records if r["customer_id"] == customer_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@bp.get("/standing-orders/<oid>")
@require_roles(*ALL)
def get_standing_order(oid):
    return success(serialize(_get_order(oid)), "object", 200)


@bp.get("/standing-orders/<oid>/projection")
@require_roles("Grower", "OpsManager")
def order_projection(oid):
    order = _get_order(oid)
    lines = [
        li for li in db.order_items.values() if li["standing_order_id"] == order["id"]
    ]
    all_lines_total = sum(li["line_extension_cents"] for li in lines)
    # confirmed_only excludes unconfirmed DRAFT edits entirely.
    confirmed_only_total = (
        all_lines_total if order["status"] in ("CONFIRMED", "LOCKED") else 0
    )
    data = serialize(order)
    data["all_lines_total"] = all_lines_total
    data["confirmed_only_total"] = confirmed_only_total
    return success(data, "object", 200)


@bp.post("/standing-orders/<oid>/lines")
@require_roles("Chef")
def add_order_line(oid):
    order = _get_order(oid)
    _check_chef_ownership(order)
    body = get_body()
    variety_id = req_str(body, "variety_id")
    qty_kg = req_num(body, "qty_kg")
    unit_price = opt_int(body, "unit_price_cents_per_kg")
    expected_version = opt_int(body, "expected_standing_order_version")
    variety = db.varieties.get(variety_id)
    if variety is None:
        raise ApiError(404, ERR_VARIETY_NOT_FOUND, "variety_id does not exist.")
    if qty_kg <= 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "qty_kg must be positive.")
    if unit_price is not None and unit_price < 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "unit_price must be >= 0.")
    # State gate: line edits only while DRAFT or CONFIRMED.
    if order["status"] == "CANCELLED":
        raise ApiError(
            409, ERR_ORDER_NOT_EDITABLE, "Order is not editable in its current state."
        )
    # Temporal gate: a LOCKED order rejects weekly changes.
    if order["status"] == "LOCKED":
        raise ApiError(
            409, ERR_WEEKLY_CHANGE_LOCKED, "Weekly change cutoff has passed."
        )
    # Temporal gate: the variety must be LISTED to be orderable.
    if variety["stage"] != "LISTED":
        raise ApiError(
            409, ERR_VARIETY_NOT_LISTED, "Variety is not in LISTED stage."
        )
    # Fiscal gate (OCC): stale writers rejected last.
    if expected_version is not None and expected_version != order["version"]:
        raise ApiError(
            412, ERR_STALE_VERSION, "expected_standing_order_version does not match."
        )
    if unit_price is None:
        unit_price = variety["listed_price_cents_per_kg"]
    qty3 = q3(qty_kg)
    line = new_resource(
        {
            "standing_order_id": order["id"],
            "variety_id": variety_id,
            "qty_kg": qty3,
            "unit_price_cents_per_kg": unit_price,
            "line_extension_cents": line_extension_cents(qty_kg, unit_price),
            "fulfillment": "PLANNED",
        }
    )
    db.order_items[line["id"]] = line
    recompute_subtotal(order)
    touch(order)
    return success(serialize(line), "object", 201)


@bp.get("/standing-orders/<oid>/lines")
@require_roles(*ALL)
def list_order_lines(oid):
    _get_order(oid)
    records = [
        li for li in db.order_items.values() if li["standing_order_id"] == oid
    ]
    return list_response(records)


@bp.post("/standing-orders/<oid>/confirm")
@require_roles("Chef")
def confirm_standing_order(oid):
    order = _get_order(oid)
    _check_chef_ownership(order)
    body = get_body()
    expected_version = opt_int(body, "expected_standing_order_version")
    if order["status"] != "DRAFT":
        raise ApiError(
            409, ERR_INVALID_STATE, "Only a DRAFT order can be confirmed."
        )
    has_lines = any(
        li["standing_order_id"] == order["id"] for li in db.order_items.values()
    )
    if not has_lines:
        raise ApiError(409, ERR_EMPTY_ORDER, "Cannot confirm an empty order.")
    if expected_version is not None and expected_version != order["version"]:
        raise ApiError(
            412, ERR_STALE_VERSION, "expected_standing_order_version does not match."
        )
    order["status"] = "CONFIRMED"
    recompute_subtotal(order)
    touch(order)
    return success(serialize(order), "object", 200)


@bp.post("/standing-orders/<oid>/cancel")
@require_roles("Chef")
def cancel_standing_order(oid):
    order = _get_order(oid)
    _check_chef_ownership(order)
    if order["status"] == "DRAFT":
        # Draft lines are dropped outright.
        doomed = [
            lid
            for lid, li in db.order_items.items()
            if li["standing_order_id"] == order["id"]
        ]
        for lid in doomed:
            del db.order_items[lid]
    elif order["status"] == "CONFIRMED":
        # Cancel-release: PLANNED lines -> SHORTED; linked stops -> SKIPPED.
        for li in db.order_items.values():
            if (
                li["standing_order_id"] == order["id"]
                and li["fulfillment"] == "PLANNED"
            ):
                li["fulfillment"] = "SHORTED"
                touch(li)
        for stop in db.delivery_stops.values():
            if stop["standing_order_id"] == order["id"] and stop["outcome"] in (
                "SCHEDULED",
                "INCLUDED",
            ):
                stop["outcome"] = "SKIPPED"
                touch(stop)
    else:
        raise ApiError(
            409, ERR_INVALID_STATE, "Order cannot be cancelled from its current state."
        )
    order["status"] = "CANCELLED"
    touch(order)
    return success(serialize(order), "object", 200)


@bp.get("/order-items")
@require_roles(*ALL)
def list_order_items():
    standing_order_id = request.args.get("standing_order_id")
    variety_id = request.args.get("variety_id")
    fulfillment = request.args.get("fulfillment")
    records = list(db.order_items.values())
    if standing_order_id is not None:
        records = [r for r in records if r["standing_order_id"] == standing_order_id]
    if variety_id is not None:
        records = [r for r in records if r["variety_id"] == variety_id]
    if fulfillment is not None:
        records = [r for r in records if r["fulfillment"] == fulfillment]
    return list_response(records)


@bp.get("/order-items/<iid>")
@require_roles(*ALL)
def get_order_item(iid):
    rec = db.order_items.get(iid)
    if rec is None:
        raise ApiError(404, ERR_ORDER_ITEM_NOT_FOUND, "order item id does not exist.")
    return success(serialize(rec), "object", 200)
