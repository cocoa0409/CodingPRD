"""Build slots: bay booking, the two overlap semantics and the waitlist
(PRD section 3.7)."""

from flask import Blueprint

import db
import middleware
import response
import validation as v
from errors import ApiError
from services import cascade, lookup

slots_bp = Blueprint("slots", __name__, url_prefix="/upfit")

BOOKABLE_ORDER_STATES = ("RELEASED", "SCHEDULED", "IN_BUILD")


def slot_state_error(slot, expected):
    return ApiError(
        "ERR_SLOT_INVALID_STATE",
        "The slot is %s; this operation requires %s." % (slot.get("status"), expected),
    )


@slots_bp.route("/build-slots", methods=["POST"])
def create_build_slot():
    middleware.require(middleware.ROLE_PRODUCTION_SCHEDULER)
    payload = v.body()
    upfit_order_id = v.req_str(payload, "upfit_order_id")
    work_bay_id = v.req_str(payload, "work_bay_id")
    slot_type = v.req_enum(payload, "slot_type", v.SLOT_TYPE)
    start_date = v.req_date(payload, "start_date")
    end_date = v.req_date(payload, "end_date")
    queue_if_full = v.opt_bool(payload, "queue_if_full", default=False)

    order = lookup.upfit_order(upfit_order_id)
    bay = lookup.work_bay(work_bay_id)

    # 40. the booking window
    if order["build_status"] not in BOOKABLE_ORDER_STATES:
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "Bay time cannot be booked for an order at %s." % order["build_status"],
        )

    chassis_id = order.get("chassis_id")

    # 61. the truck is exclusive over a closed interval and is never queued around
    if cascade.chassis_occupancy_conflict(chassis_id, start_date, end_date):
        raise ApiError(
            "ERR_CHASSIS_OCCUPANCY_CONFLICT",
            "The bound chassis is already booked over a window touching %s..%s."
            % (start_date, end_date),
        )

    # 62. the bay is an aggregate half-open resource; a full bay may be queued
    queued = False
    booked = cascade.bay_overlap_count(work_bay_id, start_date, end_date)
    if booked >= int(bay["concurrent_capacity"]):
        if not queue_if_full:
            raise ApiError(
                "ERR_BAY_CAPACITY_CONFLICT",
                "Bay %s already has %s of %s concurrent slots over that window."
                % (work_bay_id, booked, bay["concurrent_capacity"]),
            )
        queued = True

    # 63. the truck has to exist by the time the window opens
    unit = db.chassis_units.get(chassis_id) if chassis_id else None
    if unit is not None and unit.get("availability_date"):
        if v.as_date(unit["availability_date"]) > v.as_date(start_date):
            raise ApiError(
                "ERR_CHASSIS_NOT_AVAILABLE_BY_SLOT_START",
                "The chassis is not available until %s, after the window opens on %s."
                % (unit["availability_date"], start_date),
            )

    # 64. a window must span at least one day
    if v.as_date(end_date) <= v.as_date(start_date):
        raise ApiError(
            "ERR_SLOT_DATE_RANGE_INVALID",
            "end_date must be strictly after start_date.",
        )

    # 80. bay eligibility
    body = db.body_specs.get(order.get("body_spec_id")) or {}
    if bay["status"] != "ACTIVE" or body.get("body_type") not in list(
        bay.get("supported_body_types") or []
    ):
        raise ApiError(
            "ERR_BAY_BODY_TYPE_UNSUPPORTED",
            "Bay %s cannot take a %s body in status %s."
            % (work_bay_id, body.get("body_type"), bay["status"]),
        )

    row = db.insert(
        db.build_slots,
        {
            "upfit_order_id": order["id"],
            "work_bay_id": work_bay_id,
            # copied from the order at creation and never re-derived
            "chassis_id": chassis_id,
            "slot_type": slot_type,
            "start_date": start_date,
            "end_date": end_date,
            "queue_if_full": queue_if_full,
            "status": "QUEUED" if queued else "SCHEDULED",
            "promoted_from_queue_at": None,
        },
    )
    if not queued and order["build_status"] == "RELEASED":
        order["build_status"] = "SCHEDULED"
        db.touch(order)
    return response.object_response(db.serialize(row), 201)


@slots_bp.route("/build-slots/<build_slot_id>/start", methods=["POST"])
def start_build_slot(build_slot_id):
    middleware.require(middleware.ROLE_INSTALL_TECHNICIAN)
    slot = lookup.build_slot(build_slot_id)
    if slot["status"] != "SCHEDULED":
        raise slot_state_error(slot, "SCHEDULED")

    unit = db.chassis_units.get(slot.get("chassis_id")) if slot.get("chassis_id") else None
    if unit is None or unit["status"] != "ALLOCATED":
        raise ApiError(
            "ERR_CHASSIS_INVALID_STATE",
            "Starting a slot requires the bound chassis to be at ALLOCATED.",
        )
    bay = db.work_bays.get(slot["work_bay_id"]) or {}
    if bay.get("status") != "ACTIVE":
        raise ApiError(
            "ERR_BAY_BODY_TYPE_UNSUPPORTED",
            "Bay %s is not ACTIVE." % slot["work_bay_id"],
        )

    slot["status"] = "IN_BUILD"
    db.touch(slot)
    unit["status"] = "IN_UPFIT"
    db.touch(unit)
    order = db.upfit_orders.get(slot["upfit_order_id"])
    if order is not None and order["build_status"] == "SCHEDULED":
        order["build_status"] = "IN_BUILD"
        db.touch(order)
    return response.object_response(db.serialize(slot), 200)


@slots_bp.route("/build-slots/<build_slot_id>/close", methods=["POST"])
def close_build_slot(build_slot_id):
    middleware.require(middleware.ROLE_INSTALL_TECHNICIAN)
    slot = lookup.build_slot(build_slot_id)
    if slot["status"] != "IN_BUILD":
        raise slot_state_error(slot, "IN_BUILD")

    slot["status"] = "CLOSED"
    db.touch(slot)
    order = db.upfit_orders.get(slot["upfit_order_id"])
    if order is not None:
        cascade.close_slot_bubble_up(order)
    cascade.promote_from_queue(slot["work_bay_id"])
    return response.object_response(db.serialize(slot), 200)


@slots_bp.route("/build-slots/<build_slot_id>/cancel", methods=["POST"])
def cancel_build_slot(build_slot_id):
    middleware.require(middleware.ROLE_PRODUCTION_SCHEDULER)
    payload = v.body()
    v.req_str(payload, "reason")
    slot = lookup.build_slot(build_slot_id)
    if slot["status"] not in ("QUEUED", "SCHEDULED", "IN_BUILD"):
        raise slot_state_error(slot, "QUEUED, SCHEDULED or IN_BUILD")

    was = slot["status"]
    slot["status"] = "CANCELLED"
    db.touch(slot)
    # cancelling a merely QUEUED slot releases no window, so nothing follows
    if was in ("SCHEDULED", "IN_BUILD"):
        cascade.promote_from_queue(slot["work_bay_id"])
        order = db.upfit_orders.get(slot["upfit_order_id"])
        if order is not None:
            cascade.cancel_slot_step_back(order)
    return response.object_response(db.serialize(slot), 200)


@slots_bp.route("/build-slots/<build_slot_id>", methods=["GET"])
def get_build_slot(build_slot_id):
    caller = middleware.require(*middleware.ALL_ROLES)
    slot = lookup.build_slot(build_slot_id)
    middleware.enforce_order_scope(caller, db.upfit_orders.get(slot["upfit_order_id"]))
    return response.object_response(db.serialize(slot), 200)


@slots_bp.route("/build-slots", methods=["GET"])
def list_build_slots():
    caller = middleware.require(*middleware.ALL_ROLES)
    upfit_order_id = v.filter_str("upfit_order_id")
    work_bay_id = v.filter_str("work_bay_id")
    chassis_id = v.filter_str("chassis_id")
    slot_type = v.filter_enum("slot_type", v.SLOT_TYPE)
    status = v.filter_enum("status", v.SLOT_STATUS)

    rows = middleware.scope_filter_by_order(caller, list(db.build_slots.values()))
    if upfit_order_id is not None:
        rows = [r for r in rows if r["upfit_order_id"] == upfit_order_id]
    if work_bay_id is not None:
        rows = [r for r in rows if r["work_bay_id"] == work_bay_id]
    if chassis_id is not None:
        rows = [r for r in rows if r["chassis_id"] == chassis_id]
    if slot_type is not None:
        rows = [r for r in rows if r["slot_type"] == slot_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(rows)
