"""TicketOrder endpoints."""
from flask import Blueprint

from db import store, new_id, next_seq
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_ORDER_NOT_FOUND,
    ERR_SEASON_NOT_FOUND,
    ERR_FAIRE_DAY_NOT_FOUND,
    ERR_DAY_NOT_OPENABLE,
    ERR_SEASON_INVALID_STATE,
    ERR_GROUP_SIZE_BELOW_MINIMUM,
    ERR_ORDER_NOT_UNPAID,
    ERR_STALE_VERSION,
    ERR_DAY_AT_CAPACITY,
    ERR_NOTHING_REFUNDABLE,
    ERR_ORDER_NOT_REFUNDABLE,
    ERR_REFUND_EXCEEDS_PAID,
    conflict,
)
from middleware import (
    require_roles,
    require_owner,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import price_order, mint_tickets, adjust_outstanding, tickets_sold_count
from util import req, opt, present, check_unknown, new_record, mutate, assign, touch, public_view

bp = Blueprint("ticket_orders", __name__)

ORDER_TYPES = {"DAY", "SEASON", "GROUP"}
CREATE_FIELDS = {"season_id", "order_type", "quantity", "unit_price_cents", "faire_day_id"}
PATCH_FIELDS = {"expected_order_version", "quantity", "faire_day_id"}


def load_order(oid):
    return load(store.orders, oid, ERR_ORDER_NOT_FOUND, "ticket order")


@bp.route("/ticket-orders", methods=["POST"])
def create_order():
    uid, _ = require_roles("Guest")
    body = get_body()
    # Layer 3 body FK existence, canonical order: season_id, then faire_day_id.
    if isinstance(body.get("season_id"), str):
        load(store.seasons, body["season_id"], ERR_SEASON_NOT_FOUND, "season")
    if isinstance(body.get("faire_day_id"), str):
        load(store.faire_days, body["faire_day_id"], ERR_FAIRE_DAY_NOT_FOUND, "faire day")
    check_unknown(body, CREATE_FIELDS)
    season_id = req(body, "season_id", "str")
    order_type = req(body, "order_type", "enum", enum=ORDER_TYPES)
    quantity = req(body, "quantity", "int", lo=1)
    unit_price = req(body, "unit_price_cents", "int", lo=0)
    has_day = present(body, "faire_day_id")
    if order_type == "SEASON" and has_day:
        raise ApiError(ERR_INVALID_REQUEST, 400, "SEASON orders must omit faire_day_id")
    if order_type in ("DAY", "GROUP") and not has_day:
        raise ApiError(ERR_INVALID_REQUEST, 400, "DAY/GROUP orders must include faire_day_id")
    faire_day_id = opt(body, "faire_day_id", "str")

    season = store.seasons[season_id]
    day = None
    if order_type in ("DAY", "GROUP"):
        day = store.faire_days[faire_day_id]
        if day["status"] != "OPEN_FOR_SALES":
            raise conflict(ERR_DAY_NOT_OPENABLE, "DAY/GROUP orders require an OPEN_FOR_SALES day")
    else:
        if season["status"] not in ("BUILD", "OPEN"):
            raise conflict(
                ERR_SEASON_INVALID_STATE, "SEASON orders require season BUILD or OPEN"
            )
    if order_type == "GROUP" and quantity < season["group_min_size"]:
        raise ApiError(
            ERR_GROUP_SIZE_BELOW_MINIMUM,
            422,
            "GROUP order quantity below season.group_min_size",
        )

    discount, total = price_order(season, order_type, quantity, unit_price)
    order = new_record()
    order.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "season_id": season_id,
            "buyer_email": uid,
            "order_type": order_type,
            "quantity": quantity,
            "faire_day_id": faire_day_id if order_type in ("DAY", "GROUP") else None,
            "unit_price_cents": unit_price,
            "discount_pct": discount,
            "total_cents": total,
            "refunded_cents": 0,
            "retained_cents": total,
            "payment_status": "UNPAID",
            "redemption_status": "UNREDEEMED",
        }
    )
    store.orders[order["id"]] = order
    return obj_response(public_view(order), 201)


@bp.route("/ticket-orders", methods=["GET"])
def list_orders():
    require_roles()
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.orders),
        [
            ("season_id", "season_id"),
            ("faire_day_id", "faire_day_id"),
            ("buyer_email", "buyer_email"),
            ("payment_status", "payment_status"),
        ],
    )
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(o) for o in page], limit, offset, total)


@bp.route("/ticket-orders/<oid>", methods=["GET"])
def get_order(oid):
    require_roles()
    return obj_response(public_view(load_order(oid)))


@bp.route("/ticket-orders/<oid>", methods=["PATCH"])
def patch_order(oid):
    uid, _ = require_roles("Guest")
    order = load_order(oid)
    require_owner(uid == order["buyer_email"])
    body = get_body()
    if isinstance(body.get("faire_day_id"), str):
        load(store.faire_days, body["faire_day_id"], ERR_FAIRE_DAY_NOT_FOUND, "faire day")
    check_unknown(body, PATCH_FIELDS)
    expected = req(body, "expected_order_version", "int")
    new_quantity = opt(body, "quantity", "int", lo=1)
    new_day = opt(body, "faire_day_id", "str")
    if order["order_type"] == "SEASON" and present(body, "faire_day_id"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "SEASON orders must omit faire_day_id")

    # Layer 5 state gates first; OCC last within the layer.
    if order["payment_status"] != "UNPAID":
        raise conflict(ERR_ORDER_NOT_UNPAID, "edit requires an UNPAID order")
    season = store.seasons[order["season_id"]]
    effective_day = new_day if new_day is not None else order["faire_day_id"]
    if (
        new_day is not None
        and new_day != order["faire_day_id"]
        and order["order_type"] in ("DAY", "GROUP")
    ):
        day = store.faire_days[new_day]
        if day["status"] != "OPEN_FOR_SALES":
            raise conflict(ERR_DAY_NOT_OPENABLE, "faire day must be OPEN_FOR_SALES")
    if expected != order["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_order_version does not match current version")

    effective_quantity = new_quantity if new_quantity is not None else order["quantity"]
    if order["order_type"] == "GROUP" and effective_quantity < season["group_min_size"]:
        raise ApiError(
            ERR_GROUP_SIZE_BELOW_MINIMUM,
            422,
            "GROUP order quantity below season.group_min_size",
        )

    changes = {}
    if new_quantity is not None:
        changes["quantity"] = new_quantity
    if new_day is not None and order["order_type"] in ("DAY", "GROUP"):
        changes["faire_day_id"] = effective_day
    assign(order, **changes)
    discount, total = price_order(
        season, order["order_type"], order["quantity"], order["unit_price_cents"]
    )
    assign(
        order,
        discount_pct=discount,
        total_cents=total,
        retained_cents=total - order["refunded_cents"],
    )
    touch(order)  # a successful edit increments version by exactly 1
    return obj_response(public_view(order))


@bp.route("/ticket-orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    uid, _ = require_roles("Guest")
    order = load_order(oid)
    require_owner(uid == order["buyer_email"])
    check_unknown(get_body(), set())
    if order["payment_status"] != "UNPAID":
        raise conflict(ERR_ORDER_NOT_UNPAID, "pay requires an UNPAID order")
    season = store.seasons[order["season_id"]]
    if order["order_type"] in ("DAY", "GROUP"):
        day = store.faire_days[order["faire_day_id"]]
        if tickets_sold_count(day) + order["quantity"] > season["daily_capacity"]:
            raise conflict(ERR_DAY_AT_CAPACITY, "minting would exceed the day's capacity")
    mutate(order, payment_status="PAID")
    if order["order_type"] in ("DAY", "GROUP"):
        mint_tickets(order, order["quantity"], order["faire_day_id"], "DAY")
    else:
        mint_tickets(order, order["quantity"], None, "SEASON")
    adjust_outstanding(season, order["quantity"])
    return obj_response(public_view(order))


@bp.route("/ticket-orders/<oid>/refund", methods=["POST"])
def refund_order(oid):
    require_roles("GateAgent")
    order = load_order(oid)
    body = get_body()
    check_unknown(body, {"refund_cents"})
    refund_cents = req(body, "refund_cents", "int")
    if order["payment_status"] not in ("PAID", "PARTIALLY_REFUNDED"):
        raise conflict(ERR_ORDER_NOT_UNPAID, "refund requires PAID or PARTIALLY_REFUNDED")
    if order["redemption_status"] == "FULLY_REDEEMED":
        raise conflict(ERR_NOTHING_REFUNDABLE, "a FULLY_REDEEMED order has nothing to refund")
    if order["redemption_status"] in ("RAINCHECKED", "VOID"):
        raise conflict(
            ERR_ORDER_NOT_REFUNDABLE, "a RAINCHECKED or VOID order cannot be refunded"
        )
    retained_before = order["retained_cents"]
    if refund_cents <= 0 or refund_cents > retained_before:
        raise ApiError(
            ERR_REFUND_EXCEEDS_PAID, 422, "refund_cents must be positive and <= retained_cents"
        )
    refunded = order["refunded_cents"] + refund_cents
    mutate(
        order,
        refunded_cents=refunded,
        retained_cents=order["total_cents"] - refunded,
        payment_status="REFUNDED" if refund_cents == retained_before else "PARTIALLY_REFUNDED",
    )
    return obj_response(public_view(order))
