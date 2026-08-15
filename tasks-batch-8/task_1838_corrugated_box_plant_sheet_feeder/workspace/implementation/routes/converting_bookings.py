"""ConvertingBooking endpoints."""
import math

from flask import Blueprint, request

from db import db
from errors import (
    err_booking_changeover_conflict,
    err_invalid_request,
    err_invalid_state,
    err_machine_type_mismatch,
    err_not_found,
    err_outside_shift_window,
    err_overrun_tolerance_exceeded,
)
from middleware import require_roles
from response import success_object
from services.calcs import (
    bump,
    recompute_credit_exposure,
    recompute_shift_rollup,
)
from services.serialize import serialize_converting_booking
from util import is_int, new_id, utcnow_iso
from ._helpers import get_json_body, paginate_list, require_fields

bp = Blueprint("converting_bookings", __name__)

ALL_ROLES = ("PlantAdmin", "SalesRep", "ProductionPlanner", "CustomerService", "ClaimsAdjuster", "Customer")


def _get_booking_or_404(bid):
    b = db.converting_bookings.get(bid)
    if b is None:
        raise err_not_found("converting booking not found")
    return b


def _machine_for_routing(routing_type):
    return "DIE_CUTTER" if routing_type == "DIE_CUT" else "FFG"


def _queued_status_for_routing(routing_type):
    return "DIE_CUT_QUEUED" if routing_type == "DIE_CUT" else "SLOTTED_QUEUED"


@bp.route("/api/converting-bookings", methods=["POST"])
@require_roles("ProductionPlanner")
def create_booking(_user_id, _role):
    body = get_json_body()
    require_fields(body, ["box_order_id", "work_shift_id", "start_minute", "end_minute"])

    box_order_id = body["box_order_id"]
    work_shift_id = body["work_shift_id"]
    start_minute = body["start_minute"]
    end_minute = body["end_minute"]

    # Well-formedness
    if not is_int(start_minute) or start_minute < 0:
        raise err_invalid_request("start_minute must be an integer >= 0")
    if not is_int(end_minute) or end_minute <= start_minute:
        raise err_invalid_request("end_minute must be > start_minute")

    # Existence
    order = db.box_orders.get(box_order_id)
    if order is None:
        raise err_not_found("box order not found")
    shift = db.work_shifts.get(work_shift_id)
    if shift is None:
        raise err_not_found("work shift not found")

    # State: order AWAITING_CONVERTING, shift OPEN
    if order["status"] != "AWAITING_CONVERTING":
        raise err_invalid_state(f"order status {order['status']} is not AWAITING_CONVERTING")
    if shift["status"] != "OPEN":
        raise err_invalid_state("work shift is not OPEN")

    # Machine compatibility
    expected_machine = _machine_for_routing(order["routing_type"])
    if shift["machine_code"] != expected_machine:
        raise err_machine_type_mismatch(
            f"routing {order['routing_type']} requires a {expected_machine} shift"
        )

    # Window containment (inclusive both ends)
    if start_minute < shift["start_minute"] or end_minute > shift["end_minute"]:
        raise err_outside_shift_window("booking window not contained in the shift window")

    # Append-after-latest changeover rule
    new_inks = list(order.get("ink_colors") or [])
    latest = None
    for b in db.converting_bookings.values():
        if b["work_shift_id"] != shift["id"]:
            continue
        if b["status"] == "CANCELLED":
            continue
        if latest is None or b["end_minute"] > latest["end_minute"]:
            latest = b
    if latest is not None:
        prev_inks = list(latest.get("ink_colors") or [])
        gap = 15 if prev_inks == new_inks else 45
        earliest_start = latest["end_minute"] + gap
        if start_minute < earliest_start:
            raise err_booking_changeover_conflict(
                f"booking must start at or after latest prior booking end + {gap} min changeover"
            )

    now = utcnow_iso()
    bid = new_id()
    booking = {
        "id": bid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "work_shift_id": work_shift_id,
        "box_order_id": box_order_id,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "ink_colors": list(new_inks),
        "status": "QUEUED",
    }
    db.converting_bookings[bid] = booking

    # Order transitions to *_QUEUED
    order["status"] = _queued_status_for_routing(order["routing_type"])
    bump(order)

    recompute_shift_rollup(shift)
    bump(shift)

    cust = db.customer_accounts.get(order["customer_id"])
    if cust is not None:
        recompute_credit_exposure(cust)
        bump(cust)

    return success_object(serialize_converting_booking(booking), 201)


@bp.route("/api/converting-bookings/<bid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_booking(bid, _user_id, _role):
    b = _get_booking_or_404(bid)
    return success_object(serialize_converting_booking(b), 200)


@bp.route("/api/converting-bookings", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_bookings(_user_id, _role):
    filters = {
        "work_shift_id": request.args.get("work_shift_id"),
        "box_order_id": request.args.get("box_order_id"),
        "status": request.args.get("status"),
    }
    return paginate_list(list(db.converting_bookings.values()), serialize_converting_booking, filters)


@bp.route("/api/converting-bookings/<bid>/start", methods=["POST"])
@require_roles("ProductionPlanner")
def start_booking(bid, _user_id, _role):
    b = _get_booking_or_404(bid)
    if b["status"] != "QUEUED":
        raise err_invalid_state("booking is not QUEUED")
    shift = db.work_shifts.get(b["work_shift_id"])
    if shift is None:
        raise err_not_found("work shift not found")
    if shift["status"] != "OPEN":
        raise err_invalid_state("work shift is not OPEN")

    b["status"] = "RUNNING"
    bump(b)

    order = db.box_orders.get(b["box_order_id"])
    if order is not None and order["status"] in ("DIE_CUT_QUEUED", "SLOTTED_QUEUED"):
        order["status"] = "CONVERTING"
        bump(order)
        cust = db.customer_accounts.get(order["customer_id"])
        if cust is not None:
            recompute_credit_exposure(cust)
            bump(cust)

    recompute_shift_rollup(shift)
    bump(shift)

    return success_object(serialize_converting_booking(b), 200)


@bp.route("/api/converting-bookings/<bid>/complete", methods=["POST"])
@require_roles("ProductionPlanner")
def complete_booking(bid, _user_id, _role):
    b = _get_booking_or_404(bid)
    body = get_json_body()
    require_fields(body, ["produced_qty"])

    produced_qty = body["produced_qty"]
    if not is_int(produced_qty):
        raise err_invalid_request("produced_qty must be an integer")

    if b["status"] != "RUNNING":
        raise err_invalid_state("booking is not RUNNING")

    order = db.box_orders.get(b["box_order_id"])
    if order is None:
        raise err_not_found("box order not found")

    # +/-10% inclusive band
    low = math.floor(order["quantity"] * 0.90)
    high = math.ceil(order["quantity"] * 1.10)
    if produced_qty < low or produced_qty > high:
        raise err_overrun_tolerance_exceeded(
            f"produced_qty must be within [{low}, {high}] inclusive"
        )

    b["status"] = "COMPLETED"
    bump(b)

    order["status"] = "PRODUCED"
    order["produced_qty"] = produced_qty
    bump(order)

    shift = db.work_shifts.get(b["work_shift_id"])
    if shift is not None:
        recompute_shift_rollup(shift)
        bump(shift)

    cust = db.customer_accounts.get(order["customer_id"])
    if cust is not None:
        recompute_credit_exposure(cust)
        bump(cust)

    return success_object(serialize_converting_booking(b), 200)


@bp.route("/api/converting-bookings/<bid>/cancel", methods=["POST"])
@require_roles("ProductionPlanner")
def cancel_booking(bid, _user_id, _role):
    b = _get_booking_or_404(bid)
    if b["status"] not in ("QUEUED", "RUNNING"):
        raise err_invalid_state("booking is not QUEUED or RUNNING")

    b["status"] = "CANCELLED"
    bump(b)

    # Revert the order
    order = db.box_orders.get(b["box_order_id"])
    if order is not None and order["status"] in ("DIE_CUT_QUEUED", "SLOTTED_QUEUED", "CONVERTING"):
        order["status"] = "AWAITING_CONVERTING"
        order["produced_qty"] = None
        bump(order)
        cust = db.customer_accounts.get(order["customer_id"])
        if cust is not None:
            recompute_credit_exposure(cust)
            bump(cust)

    shift = db.work_shifts.get(b["work_shift_id"])
    if shift is not None:
        recompute_shift_rollup(shift)
        bump(shift)

    return success_object(serialize_converting_booking(b), 200)
