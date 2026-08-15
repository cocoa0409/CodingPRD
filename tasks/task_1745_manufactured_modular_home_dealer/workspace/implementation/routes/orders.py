"""SalesOrder composition, pricing, options, confirm/cancel/close (PRD 3.3-3.4)."""

from flask import Blueprint, request

import calc
from db import bump, create_record, store
from errors import fail
from middleware import ALL_ROLES, require
from response import ok, ok_list
from services import (cancel_order_cascade, get_or_404, order_is_live,
                      recompute_order_pricing, ser)
from validate import Shape, get_body, pagination_params

bp = Blueprint("orders", __name__)

PLACEMENT_TYPES = ["COMMUNITY_LOT", "PRIVATE_LAND"]
FINANCING_TYPES = ["CHATTEL", "REAL_PROPERTY"]


def _list(records, filters):
    limit, offset = pagination_params()
    rows = [r for r in records if all(r.get(k) == v for k, v in filters.items())]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return ok_list([ser(r) for r in rows[offset:offset + limit]], total, limit, offset)


@bp.post("/sales-orders")
@require("SalesConsultant")
def create_sales_order(actor_id, actor_role):
    shape = Shape(get_body())
    shape.req_str("customer_id")
    shape.req_str("home_unit_id")
    shape.req_enum("placement_type", PLACEMENT_TYPES)
    shape.opt_str("lot_id")
    shape.req_enum("financing_type", FINANCING_TYPES)
    shape.req_int("agreed_home_price_cents", minimum=0)

    # (5) body foreign-key existence
    customer = unit = lot = None
    if shape.ok("customer_id"):
        customer = store.customers.get(shape.value("customer_id"))
        if customer is None:
            fail("ERR_CUSTOMER_NOT_FOUND", "Customer not found")
    if shape.ok("home_unit_id"):
        unit = store.home_units.get(shape.value("home_unit_id"))
        if unit is None:
            fail("ERR_HOME_UNIT_NOT_FOUND", "Home unit not found")
    if shape.ok("lot_id") and shape.value("lot_id") is not None:
        lot = store.lots.get(shape.value("lot_id"))
        if lot is None:
            fail("ERR_LOT_NOT_FOUND", "Lot not found")

    placement = shape.value("placement_type") if shape.ok("placement_type") else None

    # (11) lot fit (community placement only)
    if placement == "COMMUNITY_LOT" and lot is not None and unit is not None:
        model = store.home_models.get(unit["model_id"])
        if model is not None and not calc.lot_fits(
                model["section_count"], model["length_ft"],
                lot["max_sections"], lot["max_length_ft"]):
            fail("ERR_LOT_DIMENSION_INSUFFICIENT",
                 "Model sections or length exceed the lot's maxima")
    # (12) lot availability: order creation requires a RESERVED lot
    if placement == "COMMUNITY_LOT" and lot is not None and lot["status"] != "RESERVED":
        fail("ERR_LOT_NOT_AVAILABLE", "Lot must be RESERVED for order creation")
    # (13) unit availability
    if unit is not None:
        if unit["status"] not in ("AT_DEALER", "RETAIL_READY"):
            fail("ERR_HOME_UNIT_UNAVAILABLE", "Unit is not AT_DEALER or RETAIL_READY")
        if any(o["home_unit_id"] == unit["id"] and order_is_live(o)
               for o in store.sales_orders.values()):
            fail("ERR_HOME_UNIT_UNAVAILABLE",
                 "Unit is held by another non-terminal order")
    # (27) placement coherence
    if placement == "COMMUNITY_LOT" and shape.value("lot_id") is None:
        fail("ERR_PLACEMENT_MISMATCH", "COMMUNITY_LOT placement requires lot_id")
    if placement == "PRIVATE_LAND" and shape.value("lot_id") is not None:
        fail("ERR_PLACEMENT_MISMATCH", "PRIVATE_LAND placement forbids lot_id")
    # (28) financing-type coherence: a mortgage cannot sit on leased land
    if (shape.ok("financing_type") and shape.value("financing_type") == "REAL_PROPERTY"
            and placement == "COMMUNITY_LOT"):
        fail("ERR_FINANCING_TYPE_INCOMPATIBLE",
             "REAL_PROPERTY financing requires PRIVATE_LAND placement")
    shape.raise_if_errors()

    order = create_record(store.sales_orders, {
        "customer_id": customer["id"],
        "home_unit_id": unit["id"],
        "placement_type": shape.value("placement_type"),
        "lot_id": lot["id"] if lot is not None and placement == "COMMUNITY_LOT" else None,
        "financing_type": shape.value("financing_type"),
        "agreed_home_price_cents": shape.value("agreed_home_price_cents"),
        "deposit_cents": 0,
        "options_total_cents": 0,
        "discount_cents": 0,
        "doc_fee_cents": 0,
        "transport_charge_cents": 0,
        "total_price_cents": 0,
        "trade_in_credit_cents": 0,
        "amount_financed_cents": 0,
        "delay_compensation_cents": 0,
        "deal_status": "DRAFT",
        "payment_status": "UNPAID",
    })
    recompute_order_pricing(order)
    # unit reservation side effect (HomeUnit AT_DEALER|RETAIL_READY -> RESERVED)
    unit["status"] = "RESERVED"
    unit["sales_order_id"] = order["id"]
    bump(unit)
    return ok(ser(order), 201)


@bp.get("/sales-orders/<rid>")
@require(*ALL_ROLES)
def get_sales_order(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")))


@bp.get("/sales-orders")
@require(*ALL_ROLES)
def list_sales_orders(actor_id, actor_role):
    filters = {}
    for k in ("customer_id", "home_unit_id", "lot_id", "deal_status"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return _list(store.sales_orders.values(), filters)


# ------------------------------------------------------------------ options --

@bp.post("/sales-orders/<rid>/options")
@require("SalesConsultant")
def add_option(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    # (7) options may be added only while the order is DRAFT
    if order["deal_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Options may be added only to a DRAFT order")
    shape = Shape(get_body())
    shape.req_str("option_code")
    shape.req_str("description")
    shape.req_int("unit_price_cents", minimum=0)
    shape.req_int("quantity", minimum=1)
    shape.raise_if_errors()
    rec = create_record(store.order_options, {
        "sales_order_id": order["id"],
        "option_code": shape.value("option_code"),
        "description": shape.value("description"),
        "unit_price_cents": shape.value("unit_price_cents"),
        "quantity": shape.value("quantity"),
        "line_total_cents": shape.value("unit_price_cents") * shape.value("quantity"),
        "status": "ACTIVE",
    })
    recompute_order_pricing(order)
    bump(order)
    return ok(ser(rec), 201)


@bp.get("/sales-orders/<rid>/options")
@require(*ALL_ROLES)
def list_options(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    rows = [o for o in store.order_options.values() if o["sales_order_id"] == order["id"]]
    return _list(rows, {})


@bp.post("/order-options/<rid>/void")
@require("SalesConsultant")
def void_option(rid, actor_id, actor_role):
    option = get_or_404(store.order_options, rid, "ERR_ORDER_OPTION_NOT_FOUND", "Order option")
    order = store.sales_orders.get(option["sales_order_id"])
    # (7) void only while ACTIVE and the owning order is DRAFT
    if option["status"] != "ACTIVE" or order is None or order["deal_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Option cannot be voided in its current state")
    option["status"] = "VOIDED"
    bump(option)
    recompute_order_pricing(order)
    bump(order)
    return ok(ser(option))


# --------------------------------------------------------- lifecycle actions --

@bp.post("/sales-orders/<rid>/confirm")
@require("SalesConsultant")
def confirm_order(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    # (7) state precondition: confirm exists from DRAFT. The reject loop (3.4)
    # returns the order to DRAFT with payment_status still DEPOSIT_PAID, so the
    # payment dimension is not part of the confirm gate.
    if order["deal_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT order can be confirmed")
    shape = Shape(get_body())
    shape.req_int("deposit_cents", minimum=0)
    # (30) deposit sufficiency: >= round_half_up(5% * total_price_cents)
    if shape.ok("deposit_cents"):
        if shape.value("deposit_cents") < calc.min_deposit_cents(order["total_price_cents"]):
            fail("ERR_DEPOSIT_INSUFFICIENT",
                 "Deposit below round_half_up(5% of total_price_cents)")
    shape.raise_if_errors()
    order["deposit_cents"] = shape.value("deposit_cents")
    order["deal_status"] = "PENDING_SITE_EVAL"
    order["payment_status"] = "DEPOSIT_PAID"
    recompute_amount_financed_on(order)
    bump(order)
    return ok(ser(order))


def recompute_amount_financed_on(order):
    order["amount_financed_cents"] = max(
        0, order["total_price_cents"] - order["deposit_cents"] - order["trade_in_credit_cents"])


@bp.post("/sales-orders/<rid>/cancel")
@require("SalesConsultant")
def cancel_order(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    # (8) cancellation guard — TITLED/CLOSED/CANCELLED or FINANCED
    if (order["deal_status"] in ("TITLED", "CLOSED", "CANCELLED")
            or order["payment_status"] == "FINANCED"):
        fail("ERR_ORDER_NOT_CANCELLABLE",
             "Order cannot be cancelled from its current state")
    cancel_order_cascade(order)
    return ok(ser(order))


@bp.post("/sales-orders/<rid>/close")
@require("DealershipAdmin")
def close_order(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    if order["deal_status"] != "TITLED":
        fail("ERR_INVALID_STATE", "Only a TITLED order can be closed")
    order["deal_status"] = "CLOSED"
    bump(order)
    return ok(ser(order))
