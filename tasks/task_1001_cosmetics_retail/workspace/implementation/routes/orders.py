"""Orders, order lines, reservation, payment, fulfilment and cancellation."""
from flask import Blueprint, request

from db import base_record, db, public, touch
from errors import ApiError, invalid
from middleware import (
    as_bool,
    as_dt,
    as_enum,
    as_int,
    as_str,
    authenticate,
    body,
    get_customer,
    get_order,
    get_order_line,
    get_store,
    get_variant,
    own_customer,
    page,
    pagination,
    required,
)
from response import created, ok, ok_list
from services import orders as order_service
from services.pricing import order_lines, reprice_provisional
from util import iso

bp = Blueprint("orders", __name__)

CHANNELS = ("BOPIS", "SHIP_FROM_STORE")
FULFILLMENT_STATUSES = (
    "DRAFT", "RESERVED", "READY_FOR_PICKUP", "PICKED_UP", "SHIPPED", "CANCELLED",
)
PAYMENT_ACTIONS = ("AUTHORIZE", "CAPTURE")
FULFILLMENT_ACTIONS = ("MARK_READY", "HAND_OVER", "SHIP")


def _invalid_order_state(message):
    return ApiError("ERR_INVALID_ORDER_STATE", message)


@bp.post("/orders")
def create_order():
    auth = authenticate("Customer", "StoreAssociate")
    payload = body()

    customer_id = as_str(required(payload, "customer_id"), "customer_id")
    store_id = as_str(required(payload, "store_id"), "store_id")
    channel = as_enum(required(payload, "channel"), "channel", CHANNELS)

    raw_lines = required(payload, "lines")
    if not isinstance(raw_lines, list):
        raise invalid("'lines' must be an array")
    parsed_lines = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise invalid("each line must be an object")
        variant_id = as_str(required(entry, "variant_id"), "variant_id")
        quantity = as_int(required(entry, "quantity"), "quantity", minimum=1)
        parsed_lines.append((variant_id, quantity))

    pickup_slot_start = None
    raw_slot = payload.get("pickup_slot_start")
    if channel == "BOPIS":
        if raw_slot is None:
            raise invalid("'pickup_slot_start' is required for a BOPIS order")
        slot = as_dt(raw_slot, "pickup_slot_start")
        if slot.minute or slot.second or slot.microsecond:
            raise invalid("'pickup_slot_start' must land exactly on the hour")
        pickup_slot_start = iso(slot)
    elif raw_slot is not None:
        pickup_slot_start = iso(as_dt(raw_slot, "pickup_slot_start"))

    allow_partial = payload.get("allow_partial")
    allow_partial = as_bool(allow_partial, "allow_partial") if allow_partial is not None else False

    points_redeemed = payload.get("points_redeemed")
    points_redeemed = as_int(points_redeemed, "points_redeemed", minimum=0) if points_redeemed is not None else 0
    if points_redeemed % 100 != 0:
        raise invalid("'points_redeemed' must be an exact multiple of 100")

    customer = get_customer(customer_id)
    store = get_store(store_id)
    variants = [get_variant(variant_id) for variant_id, _q in parsed_lines]

    own_customer(auth, customer["id"])

    order = base_record()
    order.update({
        "customer_id": customer["id"],
        "store_id": store["id"],
        "channel": channel,
        "pickup_slot_start": pickup_slot_start,
        "allow_partial": allow_partial,
        "points_redeemed": points_redeemed,
        "fulfillment_status": "DRAFT",
        "payment_status": "UNPAID",
        "pricing_variant": "PROVISIONAL",
        "tier_at_reserve": None,
        "subtotal_cents": 0,
        "tier_discount_cents": 0,
        "discounted_subtotal_cents": 0,
        "gwp_eligible": False,
        "points_value_cents": 0,
        "total_due_cents": 0,
        "points_earned": 0,
        "refunded_cents": 0,
        "fulfilled_at": None,
    })
    db.orders[order["id"]] = order

    for variant, (_vid, quantity) in zip(variants, parsed_lines):
        order_service.make_line(order, variant, quantity, "SALE")

    reprice_provisional(order)
    return created(public(order))


@bp.get("/orders/<order_id>")
def read_order(order_id):
    auth = authenticate("MerchandisingAdmin", "StoreAssociate", "Customer")
    order = get_order(order_id)
    own_customer(auth, order["customer_id"])
    return ok(public(order))


@bp.get("/orders")
def list_orders():
    auth = authenticate("MerchandisingAdmin", "StoreAssociate", "Customer")
    limit, offset = pagination()
    customer_id = request.args.get("customer_id")
    store_id = request.args.get("store_id")
    fulfillment_status = request.args.get("fulfillment_status")

    if auth.is_customer:
        if customer_id and customer_id != auth.user_id:
            raise ApiError("ERR_FORBIDDEN_OWNERSHIP", "these orders belong to another customer")
        customer_id = auth.user_id

    records = list(db.orders.values())
    if customer_id:
        records = [o for o in records if o["customer_id"] == customer_id]
    if store_id:
        records = [o for o in records if o["store_id"] == store_id]
    if fulfillment_status:
        records = [o for o in records if o["fulfillment_status"] == fulfillment_status]
    items, total = page(records, limit, offset, public)
    return ok_list(items, limit, offset, total)


@bp.post("/orders/<order_id>/lines")
def add_line(order_id):
    auth = authenticate("Customer", "StoreAssociate")
    order = get_order(order_id)
    payload = body()

    variant_id = as_str(required(payload, "variant_id"), "variant_id")
    quantity = as_int(required(payload, "quantity"), "quantity", minimum=1)
    expected_version = as_int(
        required(payload, "expected_order_version"), "expected_order_version", minimum=0
    )

    variant = get_variant(variant_id)
    own_customer(auth, order["customer_id"])

    if order["fulfillment_status"] != "DRAFT":
        raise _invalid_order_state("lines may only be added to a DRAFT order")

    if expected_version != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION", "the order has moved since it was read")

    if variant["status"] != "ACTIVE":
        raise ApiError("ERR_VARIANT_NOT_SELLABLE", "variant %s is DISCONTINUED" % variant["id"])

    order_service.make_line(order, variant, quantity, "SALE")
    reprice_provisional(order)
    touch(order)
    return ok(public(order))


@bp.get("/order-lines/<line_id>")
def read_order_line(line_id):
    auth = authenticate("MerchandisingAdmin", "StoreAssociate", "Customer")
    line = get_order_line(line_id)
    own_customer(auth, db.orders[line["order_id"]]["customer_id"])
    return ok(public(line))


@bp.get("/order-lines")
def list_order_lines():
    auth = authenticate("MerchandisingAdmin", "StoreAssociate", "Customer")
    limit, offset = pagination()
    order_id = request.args.get("order_id")
    variant_id = request.args.get("variant_id")
    promotion_id = request.args.get("promotion_id")

    records = list(db.order_lines.values())
    if auth.is_customer:
        if order_id:
            owner = db.orders.get(order_id)
            if owner is not None and owner["customer_id"] != auth.user_id:
                raise ApiError("ERR_FORBIDDEN_OWNERSHIP", "this order belongs to another customer")
        records = [
            l for l in records
            if db.orders[l["order_id"]]["customer_id"] == auth.user_id
        ]
    if order_id:
        records = [l for l in records if l["order_id"] == order_id]
    if variant_id:
        records = [l for l in records if l["variant_id"] == variant_id]
    if promotion_id:
        records = [l for l in records if l["promotion_id"] == promotion_id]
    items, total = page(records, limit, offset, public)
    return ok_list(items, limit, offset, total)


@bp.post("/orders/<order_id>/reserve")
def reserve_order(order_id):
    auth = authenticate("Customer", "StoreAssociate")
    order = get_order(order_id)
    own_customer(auth, order["customer_id"])

    if order["fulfillment_status"] != "DRAFT":
        raise _invalid_order_state("only a DRAFT order may be reserved")

    order_service.reserve(order)
    return ok(public(order))


@bp.post("/orders/<order_id>/payments")
def order_payment(order_id):
    auth = authenticate("Customer", "StoreAssociate")
    order = get_order(order_id)
    payload = body()
    action = as_enum(required(payload, "action"), "action", PAYMENT_ACTIONS)
    own_customer(auth, order["customer_id"])

    if action == "AUTHORIZE":
        if order["payment_status"] != "UNPAID" or order["fulfillment_status"] != "RESERVED":
            raise _invalid_order_state("AUTHORIZE requires an UNPAID payment on a RESERVED order")
        order["payment_status"] = "AUTHORIZED"
    else:
        if order["payment_status"] != "AUTHORIZED" or order["fulfillment_status"] not in (
            "RESERVED", "READY_FOR_PICKUP",
        ):
            raise _invalid_order_state(
                "CAPTURE requires an AUTHORIZED payment on a RESERVED or READY_FOR_PICKUP order"
            )
        order["payment_status"] = "CAPTURED"

    touch(order)
    return ok(public(order))


@bp.post("/orders/<order_id>/fulfillment")
def order_fulfillment(order_id):
    authenticate("StoreAssociate")
    order = get_order(order_id)
    payload = body()
    action = as_enum(required(payload, "action"), "action", FULFILLMENT_ACTIONS)

    if action == "MARK_READY":
        if order["channel"] != "BOPIS" or order["fulfillment_status"] != "RESERVED":
            raise _invalid_order_state("MARK_READY requires a RESERVED BOPIS order")
        if order["payment_status"] not in ("AUTHORIZED", "CAPTURED"):
            raise _invalid_order_state("MARK_READY requires payment to be at least AUTHORIZED")
        order["fulfillment_status"] = "READY_FOR_PICKUP"
        touch(order)
        return ok(public(order))

    if action == "HAND_OVER":
        if order["channel"] != "BOPIS" or order["fulfillment_status"] != "READY_FOR_PICKUP":
            raise _invalid_order_state("HAND_OVER requires a READY_FOR_PICKUP BOPIS order")
        if order["payment_status"] != "CAPTURED":
            raise ApiError("ERR_PAYMENT_NOT_CAPTURED", "hand-over demands a CAPTURED payment")
        order["fulfillment_status"] = "PICKED_UP"
        order_service.fulfil(order)
        return ok(public(order))

    if order["channel"] != "SHIP_FROM_STORE" or order["fulfillment_status"] != "RESERVED":
        raise _invalid_order_state("SHIP requires a RESERVED SHIP_FROM_STORE order")
    if order["payment_status"] != "CAPTURED":
        raise ApiError("ERR_PAYMENT_NOT_CAPTURED", "shipment demands a CAPTURED payment")
    order["fulfillment_status"] = "SHIPPED"
    order_service.fulfil(order)
    return ok(public(order))


@bp.post("/orders/<order_id>/cancel")
def cancel_order(order_id):
    auth = authenticate("Customer", "StoreAssociate")
    order = get_order(order_id)
    body()  # optional 'reason'
    own_customer(auth, order["customer_id"])

    if order["fulfillment_status"] not in ("DRAFT", "RESERVED", "READY_FOR_PICKUP"):
        raise _invalid_order_state("a terminal order may not be cancelled")

    order_service.cancel(order)
    return ok(public(order))
