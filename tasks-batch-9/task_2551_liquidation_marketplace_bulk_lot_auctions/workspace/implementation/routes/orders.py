"""Sale orders, payments and pickup appointments (PRD 3.6, 3.7)."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.helpers import list_rows
from services import aggregates, calc, guards, logistics, lookups, orders as order_svc
from util import clock, plus_days

bp = Blueprint("orders", __name__)

READ_ALL = (
    mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.SELLER_OPS, mw.TRUST_SAFETY, mw.BUYER,
)
APPOINTMENT_READ = (mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.SELLER_OPS, mw.BUYER)


@bp.get("/liquidation/sale-orders/<order_id>")
def read_order(order_id):
    mw.authenticate(READ_ALL)
    return response.success(db.view("sale_order", lookups.sale_order(order_id)))


@bp.get("/liquidation/sale-orders")
def list_orders():
    mw.authenticate(READ_ALL)
    return list_rows(
        "sale_order",
        list(db.sale_orders.values()),
        (
            ("listing_id", "listing_id"),
            ("buyer_id", "buyer_id"),
            ("payment_status", "payment_status"),
            ("logistics_status", "logistics_status"),
            ("settlement_basis", "settlement_basis"),
        ),
    )


@bp.post("/liquidation/sale-orders/<order_id>/payments")
def pay_order(order_id):
    user_id, _role = mw.authenticate((mw.BUYER,))
    order = lookups.sale_order(order_id)
    guards.owns_order(order, user_id)
    payload = mw.body()
    amount_cents = mw.req_int(payload, "amount_cents")

    # band 9
    if order["payment_status"] not in ("UNPAID", "PARTIALLY_PAID"):
        raise ApiError("ERR_ORDER_PAYMENT_STATE_INVALID")
    # band 10
    if order["logistics_status"] == "ABANDONED":
        raise ApiError("ERR_PAYMENT_WINDOW_CLOSED")
    # band 16
    if amount_cents < 1 or amount_cents > int(order["balance_due_cents"]):
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")

    order["amount_paid_cents"] = int(order["amount_paid_cents"]) + amount_cents
    order_svc.recompute_money(order)
    if int(order["balance_due_cents"]) == 0:
        order["payment_status"] = "PAID"
        order["paid_at"] = clock.now()
    else:
        order["payment_status"] = "PARTIALLY_PAID"
    db.touch(order)
    buyer = db.buyers.get(order["buyer_id"])
    if buyer is not None:
        aggregates.recompute_buyer_exposure(buyer)
    return response.success(db.view("sale_order", order))


@bp.post("/liquidation/sale-orders/<order_id>/pickup-appointments")
def book_appointment(order_id):
    user_id, _role = mw.authenticate((mw.BUYER,))
    order = lookups.sale_order(order_id)
    guards.owns_order(order, user_id)
    payload = mw.body()
    # band 6
    warehouse = (
        lookups.warehouse(payload.get("warehouse_id"))
        if mw.present(payload, "warehouse_id") else None
    )
    carrier = (
        lookups.carrier(payload.get("carrier_id"))
        if mw.present(payload, "carrier_id") else None
    )
    # band 7
    if warehouse is None:
        raise ApiError("ERR_INVALID_REQUEST", "warehouse_id is required.")
    if carrier is None:
        raise ApiError("ERR_INVALID_REQUEST", "carrier_id is required.")
    window_start_at = mw.req_datetime(payload, "window_start_at")
    window_end_at = mw.req_datetime(payload, "window_end_at")
    if window_end_at <= window_start_at:
        raise ApiError(
            "ERR_INVALID_REQUEST", "window_end_at must be strictly later than window_start_at."
        )
    bol_number = mw.req_str(payload, "bol_number")

    # band 9
    if order["logistics_status"] != "AWAITING_APPOINTMENT":
        raise ApiError("ERR_ORDER_LOGISTICS_STATE_INVALID")
    # band 10
    if order["payment_status"] != "PAID":
        raise ApiError("ERR_ORDER_NOT_PAID")
    # band 12
    if window_end_at > order["pickup_deadline_at"]:
        raise ApiError("ERR_PICKUP_DEADLINE_PASSED")
    # band 13
    door = logistics.assign_dock_door(warehouse, window_start_at, window_end_at)
    # band 14
    logistics.check_carrier_day_capacity(carrier, window_start_at)
    # band 15
    lot = lookups.lot_of_order(order)
    if lot["warehouse_id"] != warehouse["id"]:
        raise ApiError("ERR_WAREHOUSE_MISMATCH")

    appointment = db.new_row(
        sale_order_id=order["id"],
        warehouse_id=warehouse["id"],
        carrier_id=carrier["id"],
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        dock_door_number=door,
        bol_number=bol_number,
        appointment_status="SCHEDULED",
        completed_at=None,
        picked_up_unit_count=None,
    )
    db.appointments[appointment["id"]] = appointment
    order["logistics_status"] = "APPOINTMENT_SCHEDULED"
    db.touch(order)
    return response.created(db.view("appointment", appointment))


@bp.get("/liquidation/pickup-appointments/<appointment_id>")
def read_appointment(appointment_id):
    mw.authenticate(APPOINTMENT_READ)
    return response.success(db.view("appointment", lookups.appointment(appointment_id)))


@bp.get("/liquidation/pickup-appointments")
def list_appointments():
    mw.authenticate(APPOINTMENT_READ)
    return list_rows(
        "appointment",
        list(db.appointments.values()),
        (
            ("sale_order_id", "sale_order_id"),
            ("warehouse_id", "warehouse_id"),
            ("carrier_id", "carrier_id"),
            ("appointment_status", "appointment_status"),
        ),
    )


@bp.post("/liquidation/pickup-appointments/<appointment_id>/completions")
def complete_appointment(appointment_id):
    mw.authenticate((mw.MARKETPLACE_OPS,))
    appointment = lookups.appointment(appointment_id)
    payload = mw.body()
    actual_freight_cents = mw.req_int(payload, "actual_freight_cents", minimum=0)
    picked_up_unit_count = mw.req_int(payload, "picked_up_unit_count", minimum=0)

    # band 9
    if appointment["appointment_status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_STATE_INVALID")
    # band 12
    if clock.now() < appointment["window_start_at"]:
        raise ApiError("ERR_APPOINTMENT_NOT_STARTED")

    completed_at = clock.now()
    appointment["appointment_status"] = "COMPLETED"
    appointment["completed_at"] = completed_at
    appointment["picked_up_unit_count"] = picked_up_unit_count
    db.touch(appointment)

    order = lookups.order_of_appointment(appointment)
    order["logistics_status"] = "PICKED_UP"
    order["picked_up_at"] = completed_at
    order["claim_window_closes_at"] = plus_days(completed_at, calc.CLAIM_WINDOW_DAYS)
    order_svc.settle_final(order, actual_freight_cents)
    db.touch(order)
    return response.success(db.view("appointment", appointment))


@bp.post("/liquidation/pickup-appointments/<appointment_id>/cancellations")
def cancel_appointment(appointment_id):
    user_id, role = mw.authenticate((mw.BUYER, mw.MARKETPLACE_OPS))
    appointment = lookups.appointment(appointment_id)
    order = lookups.order_of_appointment(appointment)
    if role == mw.BUYER:
        guards.owns_order(order, user_id)
    mw.body()

    # band 9
    if appointment["appointment_status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_STATE_INVALID")
    # a buyer cannot cancel a window that has already opened
    if role == mw.BUYER and clock.now() >= appointment["window_start_at"]:
        raise ApiError(
            "ERR_APPOINTMENT_STATE_INVALID",
            "The appointment window has already opened.",
        )

    appointment["appointment_status"] = "CANCELLED"
    db.touch(appointment)
    if order["logistics_status"] == "APPOINTMENT_SCHEDULED":
        order["logistics_status"] = "AWAITING_APPOINTMENT"
    db.touch(order)
    return response.success(db.view("appointment", appointment))
