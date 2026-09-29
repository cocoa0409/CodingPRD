"""Will-call staging, the bay sweep, and jobsite delivery appointments."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import response
import validate as v
from errors import ApiError
from middleware import auth, check_scope, scope_list
from services import fulfillment as fulfil_svc
from services import sourcing as sourcing_svc

bp = Blueprint("logistics", __name__)

ACCESS_TYPES = ("CURBSIDE", "DRIVEWAY", "NARROW_ALLEY", "CRANE_REQUIRED")
STAGING_READ_ROLES = ("StoreOperations", "ContractorAdmin")


def _live_reservations(order):
    return [r for r in db.where("reservations", pro_order_id=order["id"])
            if r["status"] in ("HELD", "ALLOCATED")]


def _order_owner(rec):
    order = db.get("pro_orders", rec["pro_order_id"])
    return order["pro_account_id"] if order else None


# ----------------------------------------------------------- will-call staging
@bp.post("/pro/will-call-stagings")
def create_staging():
    auth("StoreOperations")
    data = v.body()
    order = v.resolve_fk(data, "pro_order_id", "pro_orders", "ERR_PRO_ORDER_NOT_FOUND")
    if order is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'pro_order_id' is required.")
    store = v.resolve_fk(data, "store_id", "stores", "ERR_STORE_NOT_FOUND")
    if store is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'store_id' is required.")
    stage_start = v.req_datetime(data, "stage_start")
    stage_hours = v.req_int(data, "stage_hours", minimum=1)

    if order["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_ORDER_NOT_RESERVED", 409)
    if stage_hours > store["max_stage_hours"]:
        raise ApiError("ERR_STAGE_WINDOW_TOO_LONG", 422)

    expires_at = clock.add_hours(stage_start, stage_hours)
    overlapping = 0
    for other in db.where("will_call_stagings", store_id=store["id"]):
        if other["status"] not in ("SCHEDULED", "STAGED"):
            continue
        # half-open [stage_start, expires_at): adjacency is not overlap
        if other["_stage_start"] < expires_at and stage_start < other["_expires_at"]:
            overlapping += 1
    if overlapping >= store["will_call_bay_slots"]:
        raise ApiError("ERR_WILL_CALL_CAPACITY_FULL", 409)

    if order["delivery_mode"] != "WILL_CALL":
        raise ApiError("ERR_DELIVERY_MODE_MISMATCH", 422)

    rec = db.new_record("will_call_stagings", {
        "pro_order_id": order["id"],
        "store_id": store["id"],
        "stage_start": clock.fmt(stage_start),
        "stage_hours": stage_hours,
        "expires_at": clock.fmt(expires_at),
        "_stage_start": stage_start,
        "_expires_at": expires_at,
        "status": "SCHEDULED",
        "picked_up_by": None,
        "picked_up_at": None,
    })
    return response.obj(db.public(rec), 201)


@bp.get("/pro/will-call-stagings/<will_call_staging_id>")
def get_staging(will_call_staging_id):
    user_id, role = auth(*STAGING_READ_ROLES)
    staging = db.require("will_call_stagings", will_call_staging_id)
    check_scope(role, user_id, _order_owner(staging))
    return response.obj(db.public(staging))


@bp.get("/pro/will-call-stagings")
def list_stagings():
    user_id, role = auth(*STAGING_READ_ROLES)
    records = db.all_of("will_call_stagings")
    for key in ("pro_order_id", "store_id", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    records = scope_list(role, user_id, records, _order_owner)
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


@bp.post("/pro/will-call-stagings/<will_call_staging_id>/stage")
def stage_staging(will_call_staging_id):
    auth("StoreOperations")
    staging = db.require("will_call_stagings", will_call_staging_id)
    order = db.require("pro_orders", staging["pro_order_id"])
    if staging["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if order["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409)
    live = _live_reservations(order)
    if not live or any(r["status"] != "ALLOCATED" for r in live):
        raise ApiError("ERR_RESERVATIONS_NOT_ALLOCATED", 409)
    staging["status"] = "STAGED"
    db.touch(staging)
    order["fulfillment_status"] = "STAGED"
    db.touch(order)
    return response.obj(db.public(staging))


@bp.post("/pro/will-call-stagings/<will_call_staging_id>/pick-up")
def pick_up_staging(will_call_staging_id):
    auth("StoreOperations")
    staging = db.require("will_call_stagings", will_call_staging_id)
    order = db.require("pro_orders", staging["pro_order_id"])
    data = v.body()
    picked_up_by = v.req_str(data, "picked_up_by")
    if staging["status"] != "STAGED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if not clock.get_now() < staging["_expires_at"]:
        raise ApiError("ERR_INVALID_STATE", 409)
    staging["picked_up_by"] = picked_up_by
    staging["picked_up_at"] = clock.now_iso()
    staging["status"] = "PICKED_UP"
    db.touch(staging)
    fulfil_svc.consume_and_fulfil(order)
    return response.obj(db.public(staging))


@bp.post("/pro/stores/<store_id>/will-call-sweep")
def will_call_sweep(store_id):
    auth("StoreOperations")
    store = db.require("stores", store_id)
    now = clock.get_now()
    expired = 0
    released = 0
    reverted = 0
    for staging in db.where("will_call_stagings", store_id=store["id"]):
        if staging["status"] not in ("SCHEDULED", "STAGED"):
            continue
        if not staging["_expires_at"] <= now:
            continue
        staging["status"] = "EXPIRED"
        db.touch(staging)
        expired += 1
        order = db.get("pro_orders", staging["pro_order_id"])
        if order is None:
            continue
        for res in _live_reservations(order):
            sourcing_svc.release(res, "STAGING_EXPIRED")
            released += 1
        if sourcing_svc.revert_order_if_all_released(order):
            reverted += 1
    return response.obj({
        "expired_staging_count": expired,
        "released_reservation_count": released,
        "reverted_order_count": reverted,
    })


# ------------------------------------------------------- delivery appointments
@bp.post("/pro/delivery-appointments")
def create_appointment():
    auth("StoreOperations")
    data = v.body()
    order = v.resolve_fk(data, "pro_order_id", "pro_orders", "ERR_PRO_ORDER_NOT_FOUND")
    if order is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'pro_order_id' is required.")
    truck = v.resolve_fk(data, "delivery_truck_id", "delivery_trucks",
                         "ERR_DELIVERY_TRUCK_NOT_FOUND")
    if truck is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'delivery_truck_id' is required.")
    window_start = v.req_datetime(data, "window_start")
    window_end = v.req_datetime(data, "window_end")
    access_type = v.req_enum(data, "jobsite_access_type", ACCESS_TYPES)

    if order["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_ORDER_NOT_RESERVED", 409)
    if truck["status"] != "AVAILABLE":
        raise ApiError("ERR_TRUCK_OUT_OF_SERVICE", 409)
    if order.get("lift_gate_required"):
        truck_store = db.get("stores", truck["store_id"])
        yard_ok = bool(truck_store and truck_store["lift_gate_available"])
        if not truck["lift_gate_equipped"] or not yard_ok:
            raise ApiError("ERR_LIFT_GATE_UNAVAILABLE", 422)
    if access_type not in truck["access_types_supported"]:
        raise ApiError("ERR_JOBSITE_ACCESS_UNSUPPORTED", 422)
    if not window_end > window_start:
        raise ApiError("ERR_INVALID_DELIVERY_WINDOW", 422)

    buffer_minutes = truck["turnaround_buffer_minutes"]
    inflated_start = window_start - timedelta(minutes=buffer_minutes)
    inflated_end = window_end + timedelta(minutes=buffer_minutes)
    for other in db.where("delivery_appointments", delivery_truck_id=truck["id"]):
        if other["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        # the inflated interval is closed: touching at a single instant conflicts
        if inflated_start <= other["_window_end"] and other["_window_start"] <= inflated_end:
            raise ApiError("ERR_TRUCK_WINDOW_CONFLICT", 409)

    if order["delivery_mode"] != "DELIVERY":
        raise ApiError("ERR_DELIVERY_MODE_MISMATCH", 422)

    rec = db.new_record("delivery_appointments", {
        "pro_order_id": order["id"],
        "delivery_truck_id": truck["id"],
        "window_start": clock.fmt(window_start),
        "window_end": clock.fmt(window_end),
        "_window_start": window_start,
        "_window_end": window_end,
        "jobsite_access_type": access_type,
        "status": "SCHEDULED",
        "delivered_at": None,
        "cancel_reason_code": None,
    })
    return response.obj(db.public(rec), 201)


@bp.get("/pro/delivery-appointments/<delivery_appointment_id>")
def get_appointment(delivery_appointment_id):
    user_id, role = auth(*STAGING_READ_ROLES)
    appt = db.require("delivery_appointments", delivery_appointment_id)
    check_scope(role, user_id, _order_owner(appt))
    return response.obj(db.public(appt))


@bp.get("/pro/delivery-appointments")
def list_appointments():
    user_id, role = auth(*STAGING_READ_ROLES)
    records = db.all_of("delivery_appointments")
    for key in ("pro_order_id", "delivery_truck_id", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    records = scope_list(role, user_id, records, _order_owner)
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


@bp.post("/pro/delivery-appointments/<delivery_appointment_id>/confirm")
def confirm_appointment(delivery_appointment_id):
    auth("StoreOperations")
    appt = db.require("delivery_appointments", delivery_appointment_id)
    order = db.require("pro_orders", appt["pro_order_id"])
    truck = db.require("delivery_trucks", appt["delivery_truck_id"])
    if appt["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if truck["status"] != "AVAILABLE":
        raise ApiError("ERR_TRUCK_OUT_OF_SERVICE", 409)
    if order["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409)
    appt["status"] = "CONFIRMED"
    db.touch(appt)
    return response.obj(db.public(appt))


@bp.post("/pro/delivery-appointments/<delivery_appointment_id>/complete")
def complete_appointment(delivery_appointment_id):
    auth("StoreOperations")
    appt = db.require("delivery_appointments", delivery_appointment_id)
    order = db.require("pro_orders", appt["pro_order_id"])
    if appt["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if order["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409)
    live = _live_reservations(order)
    if not live:
        raise ApiError("ERR_INVALID_STATE", 409)
    appt["delivered_at"] = clock.now_iso()
    appt["status"] = "DELIVERED"
    db.touch(appt)
    fulfil_svc.consume_and_fulfil(order)
    return response.obj(db.public(appt))


@bp.post("/pro/delivery-appointments/<delivery_appointment_id>/cancel")
def cancel_appointment(delivery_appointment_id):
    auth("StoreOperations")
    appt = db.require("delivery_appointments", delivery_appointment_id)
    data = v.body()
    reason_code = v.req_str(data, "reason_code")
    if appt["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    appt["cancel_reason_code"] = reason_code
    appt["status"] = "CANCELLED"
    db.touch(appt)
    return response.obj(db.public(appt))
