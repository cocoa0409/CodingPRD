from __future__ import annotations
from datetime import timedelta

from flask import Blueprint, request

from db import db, stamp_common, bump, parse_iso, now_iso
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FK_NOT_FOUND,
    ERR_NOT_FOUND,
    ERR_CLEARANCE_NON_RETURNABLE,
    ERR_DEPOSIT_NOT_APPLICABLE,
)
from middleware import require_roles
from pagination import parse_limit_offset, paginate
from response import created, ok, list_response
from routes._helpers import get_body, require_field, as_int, fetch, clean
from services import order as osvc
from services import calc

bp = Blueprint("orders", __name__)


VALID_CHANNELS = {"BOPIS", "DELIVERY", "IN_STORE"}


# ---------------------------------------------------------------------
# Create / list / get order
# ---------------------------------------------------------------------

@bp.route("/orders", methods=["POST"])
@require_roles("StoreClerk")
def create_order():
    body = get_body()
    customer_id = require_field(body, "customer_id")
    channel = require_field(body, "channel")
    lines_in = require_field(body, "lines")

    if channel not in VALID_CHANNELS:
        raise_error(ERR_INVALID_REQUEST, f"channel must be one of {sorted(VALID_CHANNELS)}")
    if customer_id not in db.customers:
        raise_error(ERR_FK_NOT_FOUND, f"customer_id {customer_id} not found")
    if not isinstance(lines_in, list) or not lines_in:
        raise_error(ERR_INVALID_REQUEST, "lines must be a non-empty array")

    # Validate lines up-front
    parsed_lines = []
    for ln in lines_in:
        if not isinstance(ln, dict):
            raise_error(ERR_INVALID_REQUEST, "each line must be object")
        sku_id = ln.get("sku_id")
        bundle_id = ln.get("bundle_id")
        qty = ln.get("qty")
        if qty is None:
            raise_error(ERR_INVALID_REQUEST, "line qty required")
        qty_i = as_int(qty, "qty")
        if qty_i < 1:
            raise_error(ERR_INVALID_REQUEST, "qty must be >= 1")
        if (sku_id is None and bundle_id is None) or (sku_id and bundle_id):
            raise_error(
                ERR_INVALID_REQUEST, "line must reference exactly one of sku_id or bundle_id"
            )
        if sku_id and sku_id not in db.skus:
            raise_error(ERR_FK_NOT_FOUND, f"sku_id {sku_id} not found")
        if bundle_id and bundle_id not in db.bundles:
            raise_error(ERR_FK_NOT_FOUND, f"bundle_id {bundle_id} not found")
        parsed_lines.append({"sku_id": sku_id, "bundle_id": bundle_id, "qty": qty_i})

    pickup_start = body.get("pickup_window_start")
    pickup_end = body.get("pickup_window_end")
    delivery_slot_id = body.get("delivery_slot_id")

    if channel == "BOPIS":
        if not pickup_start or not pickup_end:
            raise_error(ERR_INVALID_REQUEST, "BOPIS orders require pickup_window_start/end")
    if channel == "DELIVERY":
        if not delivery_slot_id:
            raise_error(ERR_INVALID_REQUEST, "DELIVERY orders require delivery_slot_id")
        if delivery_slot_id not in db.delivery_slots:
            raise_error(ERR_FK_NOT_FOUND, f"delivery_slot_id {delivery_slot_id} not found")

    order = {
        "customer_id": customer_id,
        "fulfillment_status": "DRAFT",
        "payment_status": "UNPAID",
        "channel": channel,
        "pickup_window_start": pickup_start if channel == "BOPIS" else None,
        "pickup_window_end": pickup_end if channel == "BOPIS" else None,
        "subtotal_cents": 0,
        "helium_fee_cents": 0,
        "delivery_fee_cents": 0,
        "deposit_cents": 0,
        "grand_total_cents": 0,
        "pickup_deadline": None,
    }
    stamp_common(order)
    db.orders[order["id"]] = order

    for pl in parsed_lines:
        ol = {
            "order_id": order["id"],
            "sku_id": pl["sku_id"],
            "bundle_id": pl["bundle_id"],
            "qty": pl["qty"],
            "unit_price_cents_at_capture": 0,
            "line_total_cents": 0,
        }
        stamp_common(ol)
        ol.pop("updated_at", None)
        ol.pop("version", None)
        db.order_lines[ol["id"]] = ol

    # Tie the delivery slot to the order so the reserve check can find it via
    # delivery_slot_for(order_id) — but the slot stays AVAILABLE until reserve.
    # We DON'T set order_id on the slot until reserve; instead store the intent
    # via a private field on the order so reserve can pick it up.
    if delivery_slot_id:
        order["_delivery_slot_id"] = delivery_slot_id

    # PRD §3.4: DRAFT orders expose the provisional grand-total variant.
    osvc.recompute_provisional_totals(order)

    return created(clean(order))


@bp.route("/orders/<id>", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def get_order(id):
    return ok(clean(fetch(db.orders, id)))


@bp.route("/orders", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def list_orders():
    limit, offset = parse_limit_offset()
    customer_id = request.args.get("customer_id")
    items = list(db.orders.values())
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


@bp.route("/orders/<id>/lines", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def order_lines_list(id):
    fetch(db.orders, id)  # existence
    limit, offset = parse_limit_offset()
    items = [ol for ol in db.order_lines.values() if ol["order_id"] == id]
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


@bp.route("/order-lines", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def order_lines_all():
    limit, offset = parse_limit_offset()
    sku_id = request.args.get("sku_id")
    bundle_id = request.args.get("bundle_id")
    order_id = request.args.get("order_id")
    items = list(db.order_lines.values())
    if sku_id is not None:
        items = [o for o in items if o.get("sku_id") == sku_id]
    if bundle_id is not None:
        items = [o for o in items if o.get("bundle_id") == bundle_id]
    if order_id is not None:
        items = [o for o in items if o["order_id"] == order_id]
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


@bp.route("/order-lines/<id>", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def order_line_get(id):
    return ok(clean(fetch(db.order_lines, id)))


# ---------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------

@bp.route("/orders/<id>/reserve", methods=["POST"])
@require_roles("StoreClerk")
def order_reserve(id):
    order = fetch(db.orders, id)
    body = get_body()

    # priority 6: state
    if order["fulfillment_status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Order must be DRAFT to reserve")

    # priority 7: OCC
    osvc.check_order_occ(order, body.get("expected_order_version"))

    # DELIVERY intent: tie the pending slot to the order before checking
    slot_id_intent = order.pop("_delivery_slot_id", None)
    if slot_id_intent:
        slot = db.delivery_slots.get(slot_id_intent)
        if slot and slot["status"] == "AVAILABLE":
            slot["order_id"] = order["id"]

    osvc.do_reserve(order)
    return ok(clean(order))


@bp.route("/orders/<id>/pay", methods=["POST"])
@require_roles("StoreClerk")
def order_pay(id):
    order = fetch(db.orders, id)
    body = get_body()
    mode = body.get("mode")
    if mode not in {"DEPOSIT", "FULL"}:
        raise_error(ERR_INVALID_REQUEST, "mode must be DEPOSIT or FULL")

    if mode == "DEPOSIT":
        # state check
        if order["fulfillment_status"] != "RESERVED":
            raise_error(ERR_INVALID_STATE, "Deposit requires RESERVED fulfillment")
        # business rule (priority 18)
        has_event = osvc.event_booking_for(order["id"]) is not None
        has_rental = len(osvc.rental_contracts_for(order["id"])) > 0
        if not (has_event or has_rental):
            raise_error(ERR_DEPOSIT_NOT_APPLICABLE, "Deposit requires attached EventBooking or RentalContract")
        if order["payment_status"] != "UNPAID":
            raise_error(ERR_INVALID_STATE, "Deposit only from UNPAID")
        order["payment_status"] = "DEPOSIT_HELD"
        bump(order)
        return ok(clean(order))

    # FULL
    if order["fulfillment_status"] not in {"RESERVED", "PICKING", "READY_FOR_PICKUP"}:
        raise_error(ERR_INVALID_STATE, "FULL payment requires RESERVED/PICKING/READY_FOR_PICKUP")
    if order["payment_status"] not in {"UNPAID", "DEPOSIT_HELD"}:
        raise_error(ERR_INVALID_STATE, "FULL payment requires UNPAID/DEPOSIT_HELD")
    order["payment_status"] = "PAID"
    bump(order)
    return ok(clean(order))


@bp.route("/orders/<id>/start-picking", methods=["POST"])
@require_roles("StoreClerk")
def order_start_picking(id):
    order = fetch(db.orders, id)
    if order["fulfillment_status"] != "RESERVED":
        raise_error(ERR_INVALID_STATE, "start-picking requires RESERVED")
    if order["payment_status"] not in {"DEPOSIT_HELD", "PAID"}:
        raise_error(ERR_INVALID_STATE, "start-picking requires payment DEPOSIT_HELD or PAID")
    order["fulfillment_status"] = "PICKING"
    bump(order)
    return ok(clean(order))


@bp.route("/orders/<id>/mark-ready", methods=["POST"])
@require_roles("StoreClerk")
def order_mark_ready(id):
    order = fetch(db.orders, id)
    if order["fulfillment_status"] != "PICKING":
        raise_error(ERR_INVALID_STATE, "mark-ready requires PICKING")
    if order["channel"] != "BOPIS":
        raise_error(ERR_INVALID_STATE, "mark-ready only for BOPIS")
    order["fulfillment_status"] = "READY_FOR_PICKUP"
    bump(order)
    return ok(clean(order))


@bp.route("/orders/<id>/pickup", methods=["POST"])
@require_roles("StoreClerk")
def order_pickup(id):
    order = fetch(db.orders, id)
    # BOPIS: READY_FOR_PICKUP -> PICKED_UP (with pickup_deadline check)
    # DELIVERY / IN_STORE (per PRD §3.5 "bypass" READY_FOR_PICKUP):
    #   PICKING -> PICKED_UP
    if order["channel"] == "BOPIS":
        if order["fulfillment_status"] != "READY_FOR_PICKUP":
            raise_error(ERR_INVALID_STATE, "pickup requires READY_FOR_PICKUP")
    else:
        if order["fulfillment_status"] != "PICKING":
            raise_error(ERR_INVALID_STATE, "pickup requires PICKING for non-BOPIS")
    if order["payment_status"] != "PAID":
        raise_error(ERR_INVALID_STATE, "pickup requires PAID")
    # server clock < pickup_deadline (BOPIS only)
    if order["channel"] == "BOPIS" and order.get("pickup_deadline"):
        deadline = parse_iso(order["pickup_deadline"])
        if not (db.clock < deadline):
            raise_error(ERR_INVALID_STATE, "server clock past pickup_deadline")

    # cascade: reserved_qty -= qty, on_hand_qty -= qty per line (SKU-based),
    # and for bundles fan out.
    _pickup_stock_cascade(order)

    # cascade rentals: RESERVED -> PICKED_UP, decrement stock too
    for rc in osvc.rental_contracts_for(order["id"]):
        if rc["status"] == "RESERVED":
            rc["status"] = "PICKED_UP"
            sku = db.skus.get(rc["sku_id"])
            if sku:
                sku["reserved_qty"] = max(0, int(sku["reserved_qty"]) - int(rc["qty"]))
                sku["on_hand_qty"] = max(0, int(sku["on_hand_qty"]) - int(rc["qty"]))
                bump(sku)
            bump(rc)

    order["fulfillment_status"] = "PICKED_UP"
    bump(order)
    # Track the pickup timestamp for the 14-day return window
    db.order_picked_up_at[order["id"]] = db.clock
    return ok(clean(order))


def _pickup_stock_cascade(order: dict) -> None:
    lines = osvc.order_lines_for(order["id"])
    demand: dict[str, int] = {}
    for ln in lines:
        q = int(ln["qty"])
        if ln.get("sku_id"):
            demand[ln["sku_id"]] = demand.get(ln["sku_id"], 0) + q
        elif ln.get("bundle_id"):
            for sku_id, bl_qty in _bundle_sku_totals(ln["bundle_id"]).items():
                demand[sku_id] = demand.get(sku_id, 0) + bl_qty * q
    for sku_id, q in demand.items():
        sku = db.skus.get(sku_id)
        if sku is None:
            continue
        sku["reserved_qty"] = max(0, int(sku["reserved_qty"]) - q)
        sku["on_hand_qty"] = max(0, int(sku["on_hand_qty"]) - q)
        bump(sku)


def _bundle_sku_totals(bundle_id: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for bl in db.bundle_lines.values():
        if bl["bundle_id"] == bundle_id:
            out[bl["sku_id"]] = out.get(bl["sku_id"], 0) + int(bl["qty"])
    return out


@bp.route("/orders/<id>/deliver", methods=["POST"])
@require_roles("DeliveryDriver")
def order_deliver(id):
    order = fetch(db.orders, id)
    if order["channel"] != "DELIVERY":
        raise_error(ERR_INVALID_STATE, "deliver only for DELIVERY orders")
    if order["fulfillment_status"] != "PICKED_UP":
        raise_error(ERR_INVALID_STATE, "deliver requires PICKED_UP")
    slot = osvc.delivery_slot_for(order["id"])
    if slot is None:
        raise_error(ERR_INVALID_STATE, "no delivery slot")
    ws = parse_iso(slot["window_start"])
    we = parse_iso(slot["window_end"])
    if not (ws <= db.clock < we):
        raise_error(ERR_INVALID_STATE, "server clock outside delivery slot window")
    slot["status"] = "COMPLETED"
    bump(slot)
    order["fulfillment_status"] = "DELIVERED"
    bump(order)
    return ok(clean(order))


@bp.route("/orders/<id>/return", methods=["POST"])
@require_roles("StoreClerk")
def order_return(id):
    order = fetch(db.orders, id)
    # state (priority 6)
    if order["fulfillment_status"] not in {"PICKED_UP", "DELIVERED"}:
        raise_error(ERR_INVALID_STATE, "return requires PICKED_UP or DELIVERED")

    # 14-day return window: uses pickup timestamp + 14 days
    pickup_at = db.order_picked_up_at.get(order["id"])
    if pickup_at is not None:
        deadline = pickup_at + timedelta(seconds=14 * 86400)
        if db.clock > deadline:
            raise_error(ERR_INVALID_STATE, "return window expired")

    # priority 8: clearance non-returnable
    for ln in osvc.order_lines_for(order["id"]):
        if ln.get("sku_id"):
            sku = db.skus.get(ln["sku_id"])
            if sku and sku.get("is_clearance"):
                raise_error(
                    ERR_CLEARANCE_NON_RETURNABLE,
                    "Order contains clearance line — non-returnable",
                )

    # Restore on_hand for each line's SKU (bundles fan out)
    for ln in osvc.order_lines_for(order["id"]):
        q = int(ln["qty"])
        if ln.get("sku_id"):
            sku = db.skus.get(ln["sku_id"])
            if sku:
                sku["on_hand_qty"] = int(sku["on_hand_qty"]) + q
                bump(sku)
        elif ln.get("bundle_id"):
            for sku_id, bl_qty in _bundle_sku_totals(ln["bundle_id"]).items():
                sku = db.skus.get(sku_id)
                if sku:
                    sku["on_hand_qty"] = int(sku["on_hand_qty"]) + bl_qty * q
                    bump(sku)

    # Refund → store credit
    cust = db.customers.get(order["customer_id"])
    if cust is not None:
        cust["store_credit_cents"] = int(cust.get("store_credit_cents", 0)) + int(
            order.get("grand_total_cents", 0)
        )
        bump(cust)

    order["payment_status"] = "REFUNDED"
    order["fulfillment_status"] = "RETURNED"
    bump(order)
    return ok(clean(order))


@bp.route("/orders/<id>/cancel", methods=["POST"])
@require_roles("StoreClerk")
def order_cancel(id):
    order = fetch(db.orders, id)
    if order["fulfillment_status"] not in {"DRAFT", "RESERVED", "PICKING"}:
        raise_error(ERR_INVALID_STATE, "cancel requires DRAFT/RESERVED/PICKING")

    if order["fulfillment_status"] in {"RESERVED", "PICKING"}:
        osvc.release_reservation(order)
    if order["payment_status"] == "DEPOSIT_HELD":
        order["payment_status"] = "REFUNDED"
    order["fulfillment_status"] = "CANCELLED"
    bump(order)
    return ok(clean(order))
