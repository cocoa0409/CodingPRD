"""Shipment endpoints."""

from datetime import date

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services.cascade as cascade

bp = Blueprint("shipments", __name__)

VALID_FREIGHT_CLASSES = {"STANDARD", "OVERSIZE", "HEAVY_HAUL"}


def _occupancy_end(shipment, slot):
    return shipment["lift_start_hour"] + shipment["lift_hours"] + slot["buffer_hours"]


def _intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.route("/genset-packaging/shipments", methods=["POST"])
def create_shipment():
    mw.require_roles("LogisticsCoordinator")
    body = mw.get_json_body()

    order_id = mw.require_string(body, "order_id")
    crane_slot_id = mw.require_string(body, "crane_slot_id")
    lift_start_hour = mw.require_number(body, "lift_start_hour")
    lift_hours = mw.require_number(body, "lift_hours", minimum=0, exclusive_minimum=True)
    gross_weight_kg = mw.require_int(body, "gross_weight_kg", minimum=1)
    freight_class = mw.require_enum(body, "freight_class", VALID_FREIGHT_CLASSES)
    expected_crane_slot_version = mw.require_int(body, "expected_crane_slot_version", minimum=1)

    # Existence
    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Package order not found")
    slot = db.crane_slots.get(crane_slot_id)
    if slot is None:
        raise errors.not_found("Crane slot not found")

    # OCC check on crane slot version
    if slot["version"] != expected_crane_slot_version:
        raise errors.ApiError(
            errors.ERR_STALE_CRANE_SLOT_VERSION, 412,
            "expected_crane_slot_version does not match the slot's current version",
        )

    # Build state gate: order must be READY_TO_SHIP
    if order["build_status"] != "READY_TO_SHIP":
        raise errors.ApiError(
            errors.ERR_INVALID_BUILD_STATE, 409,
            "Order build_status must be READY_TO_SHIP to book a shipment",
        )

    # Crane window overlap: occupancy = [lift_start, lift_start + lift_hours + buffer)
    occ_start = lift_start_hour
    occ_end = lift_start_hour + lift_hours + slot["buffer_hours"]

    # Must not exceed the slot window
    if occ_start < slot["window_start_hour"] or occ_end > slot["window_end_hour"]:
        raise errors.ApiError(
            errors.ERR_CRANE_WINDOW_OVERLAP, 409,
            "Lift occupancy exceeds the crane slot window",
        )

    # Check against existing active bookings (BOOKED, DISPATCHED)
    for existing in db.shipments.values():
        if (
            existing["crane_slot_id"] == crane_slot_id
            and existing["status"] in ("BOOKED", "DISPATCHED")
        ):
            ex_start = existing["lift_start_hour"]
            ex_end = _occupancy_end(existing, slot)
            if _intervals_overlap(occ_start, occ_end, ex_start, ex_end):
                raise errors.ApiError(
                    errors.ERR_CRANE_WINDOW_OVERLAP, 409,
                    "Lift occupancy intersects an existing booking on the same slot",
                )

    record = {
        "order_id": order_id,
        "crane_slot_id": crane_slot_id,
        "lift_start_hour": lift_start_hour,
        "lift_hours": lift_hours,
        "gross_weight_kg": gross_weight_kg,
        "freight_class": freight_class,
        "status": "BOOKED",
    }
    db.stamp_new(record)
    db.shipments[record["id"]] = record

    # Update crane slot accounting
    slot["reserved_hours"] += lift_hours + slot["buffer_hours"]
    slot["free_hours"] = (slot["window_end_hour"] - slot["window_start_hour"]) - slot["reserved_hours"]
    db.touch(slot)

    return resp.success_created(record)


@bp.route("/genset-packaging/shipments/<shipmentId>", methods=["GET"])
def get_shipment(shipmentId):
    mw.authenticate()
    record = db.shipments.get(shipmentId)
    if record is None:
        raise errors.not_found("Shipment not found")
    return resp.success_object(record)


@bp.route("/genset-packaging/shipments", methods=["GET"])
def list_shipments():
    mw.authenticate()
    limit, offset = mw.parse_pagination()

    items = list(db.shipments.values())
    for param in ("order_id", "crane_slot_id"):
        val = mw.request.args.get(param)
        if val:
            items = [s for s in items if s.get(param) == val]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.success_list(page, limit, offset, total)


@bp.route("/genset-packaging/shipments/<shipmentId>/dispatch", methods=["POST"])
def dispatch_shipment(shipmentId):
    mw.require_roles("LogisticsCoordinator")

    shipment = db.shipments.get(shipmentId)
    if shipment is None:
        raise errors.not_found("Shipment not found")

    if shipment["status"] != "BOOKED":
        raise errors.ApiError(
            errors.ERR_SHIPMENT_STATE_INVALID, 409,
            "Shipment must be BOOKED to dispatch",
        )

    # Clock gate: current logical date >= slot service_date
    slot = db.crane_slots.get(shipment["crane_slot_id"])
    if slot is None:
        raise errors.not_found("Crane slot not found")
    today = date.fromisoformat(db.logical_today())
    slot_date = date.fromisoformat(slot["service_date"])
    if today < slot_date:
        raise errors.ApiError(
            errors.ERR_SHIPMENT_DATE_NOT_REACHED, 422,
            "Current logical-clock date has not reached the crane slot service_date",
        )

    shipment["status"] = "DISPATCHED"
    db.touch(shipment)
    return resp.success_object(shipment)


@bp.route("/genset-packaging/shipments/<shipmentId>/deliver", methods=["POST"])
def deliver_shipment(shipmentId):
    mw.require_roles("LogisticsCoordinator")

    shipment = db.shipments.get(shipmentId)
    if shipment is None:
        raise errors.not_found("Shipment not found")

    if shipment["status"] != "DISPATCHED":
        raise errors.ApiError(
            errors.ERR_SHIPMENT_STATE_INVALID, 409,
            "Shipment must be DISPATCHED to deliver",
        )

    shipment["status"] = "DELIVERED"
    db.touch(shipment)

    # Cascade: order build READY_TO_SHIP -> DELIVERED; commercial AUTHORIZED -> INVOICED
    order = db.orders.get(shipment["order_id"])
    if order is not None:
        if order["build_status"] == "READY_TO_SHIP":
            order["build_status"] = "DELIVERED"
            db.touch(order)
        if order["commercial_status"] == "AUTHORIZED":
            order["commercial_status"] = "INVOICED"
            db.touch(order)

    return resp.success_object(shipment)


@bp.route("/genset-packaging/shipments/<shipmentId>/release", methods=["POST"])
def release_shipment_endpoint(shipmentId):
    mw.require_roles("LogisticsCoordinator")

    shipment = db.shipments.get(shipmentId)
    if shipment is None:
        raise errors.not_found("Shipment not found")

    if shipment["status"] != "BOOKED":
        raise errors.ApiError(
            errors.ERR_SHIPMENT_STATE_INVALID, 409,
            "Shipment must be BOOKED to release",
        )

    cascade.release_shipment(shipment)
    return resp.success_object(shipment)
