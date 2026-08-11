"""SalesOrder routes — cut-off, delivery-window overlap, credit gate,
confirm/hold branching, pick/deliver cold-chain gates, cancellation."""

from datetime import timedelta, time as dtime

from flask import Blueprint

from db import store
from errors import (
    raise_error,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_CUTOFF_PASSED,
    ERR_WINDOW_OVERLAP,
    ERR_CUSTOMER_INACTIVE,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_INSUFFICIENT_QUANTITY,
    ERR_LOT_NOT_ACCEPTED,
    ERR_COLD_CHAIN_VIOLATION,
    ERR_FORBIDDEN,
)
from middleware import require_roles, check_customer_ownership, ALL_ROLES
from response import success_object, success_list
from services.domain import (
    get_json_body,
    require_fields,
    req_date,
    req_time_hhmm,
    req_positive_number,
    req_positive_int,
    is_int,
    is_str,
    lookup,
    stamp_new,
    touch,
    paginate,
    sorted_by_created,
    order_line_extended_cents,
    recompute_lot_available,
    recompute_customer_credit_exposure,
    clock_now,
    DATE_FMT,
)

bp = Blueprint("orders", __name__)

CUTOFF_TIME = dtime(14, 0, 0)


@bp.post("/market/sales-orders")
def create_sales_order():
    user_id, role = require_roles(["SalesDesk", "CustomerRep"])
    body = get_json_body()
    require_fields(
        body, ["customer_id", "delivery_date", "window_start", "window_end", "lines"]
    )
    customer_id = body.get("customer_id")
    if not is_str(customer_id):
        raise_error(ERR_VALIDATION, "customer_id must be a string")
    delivery_date = req_date(body, "delivery_date")
    window_start = req_time_hhmm(body, "window_start")
    window_end = req_time_hhmm(body, "window_end")
    if window_end <= window_start:
        raise_error(ERR_VALIDATION, "window_end must be after window_start")
    pallet_count = body.get("pallet_count", 1)
    if not is_int(pallet_count) or pallet_count <= 0:
        raise_error(ERR_VALIDATION, "pallet_count must be a positive integer")
    lines_raw = body.get("lines")
    if not isinstance(lines_raw, list) or len(lines_raw) == 0:
        raise_error(ERR_VALIDATION, "lines must be a non-empty array")
    lines = []
    for i, raw in enumerate(lines_raw):
        if not isinstance(raw, dict):
            raise_error(ERR_VALIDATION, f"lines[{i}] must be an object")
        lot_id = raw.get("lot_id")
        if not is_str(lot_id):
            raise_error(ERR_VALIDATION, f"lines[{i}].lot_id must be a string")
        quantity = raw.get("quantity")
        if not is_int(quantity) or quantity <= 0:
            raise_error(ERR_VALIDATION, f"lines[{i}].quantity must be a positive integer")
        if "unit_price" not in raw or raw["unit_price"] is None:
            raise_error(ERR_VALIDATION, f"lines[{i}].unit_price is required")
        unit_price = req_positive_number(raw, "unit_price")
        lines.append(
            {
                "lot_id": lot_id,
                "quantity": quantity,
                "unit_price": float(unit_price),
            }
        )

    # FK existence: customer first, then line lots (priority 4)
    customer = lookup(store.customers, customer_id, "Customer")
    for line in lines:
        lookup(store.purchase_lots, line["lot_id"], "PurchaseLot")

    # CustomerRep may only create for own customer_id (priority 2 ownership)
    check_customer_ownership(user_id, role, customer_id)

    # Priority 6 cross-entity state gates
    if customer["status"] != "ACTIVE":
        raise_error(ERR_CUSTOMER_INACTIVE, "Customer is not ACTIVE")
    for line in lines:
        lot = store.purchase_lots[line["lot_id"]]
        if lot["status"] != "ACCEPTED":
            raise_error(
                ERR_LOT_NOT_ACCEPTED,
                f"Line lot {lot['id']} is not ACCEPTED (status {lot['status']})",
            )

    # Priority 8 temporal: cut-off.
    now = clock_now()
    clock_date = now.date()
    delivery_date_str = delivery_date.strftime(DATE_FMT)
    if delivery_date <= clock_date:
        raise_error(
            ERR_CUTOFF_PASSED,
            "delivery_date must be later than the current clock date",
        )
    if delivery_date == clock_date + timedelta(days=1) and now.time() > CUTOFF_TIME:
        raise_error(
            ERR_CUTOFF_PASSED,
            "Next-day delivery cut-off (14:00) has passed",
        )

    # Priority 8 temporal: per-customer delivery-window overlap on the same
    # delivery_date, excluding CANCELLED and INVOICED orders.
    for order in store.sales_orders.values():
        if order["customer_id"] != customer_id:
            continue
        if order["status"] in {"CANCELLED", "INVOICED"}:
            continue
        if order["delivery_date"] != delivery_date_str:
            continue
        o_start = _hhmm_to_min(order["window_start"])
        o_end = _hhmm_to_min(order["window_end"])
        if window_start < o_end and o_start < window_end:
            raise_error(
                ERR_WINDOW_OVERLAP,
                "Delivery window overlaps an existing order's window on this date",
            )

    # Priority 9 domain: line availability at creation time.
    for line in lines:
        lot = store.purchase_lots[line["lot_id"]]
        recompute_lot_available(lot)
        if line["quantity"] > lot["available_units"]:
            raise_error(
                ERR_INSUFFICIENT_QUANTITY,
                f"Line quantity {line['quantity']} exceeds lot available_units {lot['available_units']}",
            )

    # order_subtotal: per-line round half-up to cents, THEN sum (pinned).
    from decimal import Decimal

    subtotal = sum(
        order_line_extended_cents(Decimal(str(line["unit_price"])), line["quantity"])
        for line in lines
    )

    order = stamp_new(
        {
            "customer_id": customer_id,
            "delivery_date": delivery_date_str,
            "window_start": _min_to_hhmm(window_start),
            "window_end": _min_to_hhmm(window_end),
            "pallet_count": pallet_count,
            "lines": lines,
            "status": "PENDING",
            "hold_reason": None,
            "subtotal_cents": subtotal,
        }
    )
    store.sales_orders[order["id"]] = order
    return success_object(order, 201)


def _hhmm_to_min(s):
    parts = s.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _min_to_hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


@bp.get("/market/sales-orders/<order_id>")
def get_sales_order(order_id):
    user_id, role = require_roles(ALL_ROLES)
    order = lookup(store.sales_orders, order_id, "SalesOrder")
    check_customer_ownership(user_id, role, order["customer_id"])
    return success_object(order, 200)


def _check_lines_ok(order):
    """Confirm-time line gates: lot ACCEPTED + quantity <= available."""
    for line in order["lines"]:
        lot = store.purchase_lots.get(line["lot_id"])
        if lot is None:
            from errors import ERR_NOT_FOUND

            raise_error(ERR_NOT_FOUND, f"PurchaseLot not found: {line['lot_id']}")
        if lot["status"] != "ACCEPTED":
            raise_error(
                ERR_LOT_NOT_ACCEPTED,
                f"Line lot {lot['id']} is not ACCEPTED (status {lot['status']})",
            )
    for line in order["lines"]:
        lot = store.purchase_lots[line["lot_id"]]
        recompute_lot_available(lot)
        if line["quantity"] > lot["available_units"]:
            raise_error(
                ERR_INSUFFICIENT_QUANTITY,
                f"Line quantity {line['quantity']} exceeds lot available_units {lot['available_units']}",
            )


@bp.post("/market/sales-orders/<order_id>/confirm")
def confirm_sales_order(order_id):
    require_roles(["SalesDesk"])
    order = lookup(store.sales_orders, order_id, "SalesOrder")
    if order["status"] not in {"PENDING", "ON_HOLD"}:
        raise_error(
            ERR_INVALID_STATE,
            f"Order must be PENDING or ON_HOLD to confirm; current status {order['status']}",
        )
    if order["status"] == "ON_HOLD" and order["hold_reason"] != "CREDIT":
        # A COLD_CHAIN hold can only be cancelled, never confirmed.
        raise_error(
            ERR_INVALID_STATE,
            "Only a CREDIT hold may be released via confirm",
        )
    customer = lookup(store.customers, order["customer_id"], "Customer")
    if customer["status"] != "ACTIVE":
        raise_error(ERR_CUSTOMER_INACTIVE, "Customer is not ACTIVE")
    _check_lines_ok(order)
    # Money gate last: exposure + subtotal <= limit (equality allowed).
    recompute_customer_credit_exposure(customer["id"])
    if customer["credit_exposure_cents"] + order["subtotal_cents"] > customer["credit_limit_cents"]:
        raise_error(
            ERR_CREDIT_LIMIT_EXCEEDED,
            "Confirm would exceed the customer's credit limit",
        )
    for line in order["lines"]:
        lot = store.purchase_lots[line["lot_id"]]
        lot["reserved_units"] += line["quantity"]
        recompute_lot_available(lot)
        touch(lot)
    order["status"] = "CONFIRMED"
    order["hold_reason"] = None
    touch(order)
    recompute_customer_credit_exposure(customer["id"])
    return success_object(order, 200)


def _check_cold_chain_ok(order):
    for line in order["lines"]:
        lot = store.purchase_lots.get(line["lot_id"])
        if lot is not None and lot["cold_chain_status"] != "OK":
            raise_error(
                ERR_COLD_CHAIN_VIOLATION,
                f"Line lot {lot['id']} has cold_chain_status VIOLATED",
            )


@bp.post("/market/sales-orders/<order_id>/pick")
def pick_sales_order(order_id):
    require_roles(["Receiver"])
    order = lookup(store.sales_orders, order_id, "SalesOrder")
    if order["status"] != "CONFIRMED":
        raise_error(
            ERR_INVALID_STATE,
            f"Order must be CONFIRMED to pick; current status {order['status']}",
        )
    _check_cold_chain_ok(order)
    order["status"] = "PICKED"
    touch(order)
    return success_object(order, 200)


@bp.post("/market/sales-orders/<order_id>/deliver")
def deliver_sales_order(order_id):
    require_roles(["Receiver"])
    order = lookup(store.sales_orders, order_id, "SalesOrder")
    if order["status"] != "PICKED":
        raise_error(
            ERR_INVALID_STATE,
            f"Order must be PICKED to deliver; current status {order['status']}",
        )
    _check_cold_chain_ok(order)
    for line in order["lines"]:
        lot = store.purchase_lots.get(line["lot_id"])
        if lot is None:
            continue
        lot["reserved_units"] = max(0, lot["reserved_units"] - line["quantity"])
        lot["sold_units"] += line["quantity"]
        recompute_lot_available(lot)
        touch(lot)
    order["status"] = "DELIVERED"
    touch(order)
    recompute_customer_credit_exposure(order["customer_id"])
    return success_object(order, 200)


@bp.post("/market/sales-orders/<order_id>/cancel")
def cancel_sales_order(order_id):
    user_id, role = require_roles(["SalesDesk", "CustomerRep"])
    order = lookup(store.sales_orders, order_id, "SalesOrder")
    if role == "CustomerRep":
        # CustomerRep: own orders only, and only while PENDING.
        check_customer_ownership(user_id, role, order["customer_id"])
        if order["status"] != "PENDING":
            raise_error(
                ERR_FORBIDDEN,
                "CustomerRep may cancel only own PENDING orders",
            )
    if order["status"] not in {"PENDING", "CONFIRMED", "ON_HOLD"}:
        raise_error(
            ERR_INVALID_STATE,
            f"Order cannot be cancelled from status {order['status']}",
        )
    if order["status"] == "CONFIRMED":
        # Release reservations still held by this order. (ON_HOLD orders of
        # either reason already released their reservations at hold time.)
        for line in order["lines"]:
            lot = store.purchase_lots.get(line["lot_id"])
            if lot is None:
                continue
            lot["reserved_units"] = max(0, lot["reserved_units"] - line["quantity"])
            recompute_lot_available(lot)
            touch(lot)
    order["status"] = "CANCELLED"
    order["hold_reason"] = None
    touch(order)
    recompute_customer_credit_exposure(order["customer_id"])
    return success_object(order, 200)
