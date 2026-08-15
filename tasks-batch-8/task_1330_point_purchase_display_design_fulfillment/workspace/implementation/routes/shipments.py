"""Shipment endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles, get_auth
from services.common import (
    new_common_fields, require_string, touch, paginate, sort_by_created,
    serialize, parse_iso,
)

bp = Blueprint("shipments", __name__)

GET_SHIPMENT_ROLES = ("PlatformAdmin", "ProgramManager", "LogisticsCoordinator", "WarehouseOperator")

DELIVERY_GRACE_DAYS = 7


def _get_shipment_or_404(shipment_id):
    s = db.shipments.get(shipment_id)
    if not s:
        raise errors.err_not_found("Shipment not found")
    return s


@bp.route("/pop/shipments", methods=["POST"])
@require_roles("LogisticsCoordinator")
def create_shipment():
    body = request.get_json(silent=True) or {}
    kit_id = require_string(body, "kit_id")
    ship_window_start_raw = require_string(body, "ship_window_start")
    ship_window_end_raw = require_string(body, "ship_window_end")
    ship_window_start = parse_iso(ship_window_start_raw)
    ship_window_end = parse_iso(ship_window_end_raw)
    if ship_window_end <= ship_window_start:
        raise errors.err_invalid_request("ship_window_end must be after ship_window_start")

    kit = db.kits.get(kit_id)
    if not kit:
        raise errors.err_not_found("Kit not found")

    appointment_at_raw = body.get("appointment_at")
    appointment_at = None
    if appointment_at_raw is not None:
        appointment_at = parse_iso(appointment_at_raw)

    shipment = new_common_fields()
    shipment.update({
        "kit_id": kit_id,
        "ship_window_start": ship_window_start_raw,
        "ship_window_end": ship_window_end_raw,
        "appointment_at": appointment_at_raw,
        "shipped_at": None,
        "delivered_at": None,
        "status": "SCHEDULED",
        "_window_start_dt": ship_window_start,
        "_window_end_dt": ship_window_end,
        "_appointment_dt": appointment_at,
    })
    db.shipments[shipment["id"]] = shipment
    return response.success_object(serialize(shipment), 201)


@bp.route("/pop/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    _, role = get_auth()
    if role not in GET_SHIPMENT_ROLES:
        raise errors.err_unauthorized()
    shipment = _get_shipment_or_404(shipment_id)
    return response.success_object(serialize(shipment), 200)


@bp.route("/pop/kits/<kit_id>/shipments", methods=["GET"])
def list_kit_shipments(kit_id):
    _, role = get_auth()
    if role not in GET_SHIPMENT_ROLES:
        raise errors.err_unauthorized()
    if not db.kits.get(kit_id):
        raise errors.err_not_found("Kit not found")
    items = sort_by_created([s for s in db.shipments.values() if s["kit_id"] == kit_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(s) for s in page], limit, offset, total)


@bp.route("/pop/shipments/<shipment_id>/set-appointment", methods=["POST"])
@require_roles("LogisticsCoordinator")
def set_appointment(shipment_id):
    shipment = _get_shipment_or_404(shipment_id)
    if shipment["status"] != "SCHEDULED":
        raise errors.err_invalid_state("Shipment is not in SCHEDULED")
    body = request.get_json(silent=True) or {}
    appointment_at_raw = require_string(body, "appointment_at")
    appointment_at = parse_iso(appointment_at_raw)
    if appointment_at < shipment["_window_start_dt"] or appointment_at > shipment["_window_end_dt"]:
        raise errors.err_window_violation("appointment_at is outside the ship window")
    shipment["appointment_at"] = appointment_at_raw
    shipment["_appointment_dt"] = appointment_at
    shipment["status"] = "APPOINTMENT_SET"
    touch(shipment)
    return response.success_object(serialize(shipment), 200)


@bp.route("/pop/shipments/<shipment_id>/ship", methods=["POST"])
@require_roles("LogisticsCoordinator")
def ship(shipment_id):
    shipment = _get_shipment_or_404(shipment_id)
    if shipment["status"] != "APPOINTMENT_SET":
        raise errors.err_invalid_state("Shipment is not in APPOINTMENT_SET")
    kit = db.kits.get(shipment["kit_id"])
    if not kit or kit["status"] != "KITTED":
        raise errors.err_invalid_state("Parent kit is not in KITTED")
    now = db.get_clock()
    if now < shipment["_window_start_dt"]:
        raise errors.err_window_violation("Cannot ship before ship_window_start")
    shipment["status"] = "SHIPPED"
    shipment["shipped_at"] = db.now_iso()
    touch(shipment)
    kit["status"] = "SHIPPED"
    touch(kit)
    return response.success_object(serialize(shipment), 200)


@bp.route("/pop/shipments/<shipment_id>/deliver", methods=["POST"])
@require_roles("LogisticsCoordinator")
def deliver(shipment_id):
    shipment = _get_shipment_or_404(shipment_id)
    if shipment["status"] != "SHIPPED":
        raise errors.err_invalid_state("Shipment is not in SHIPPED")
    now = db.get_clock()
    if now > shipment["_window_end_dt"] + timedelta(days=DELIVERY_GRACE_DAYS):
        raise errors.err_window_violation("Delivery is past ship_window_end + 7 day grace")
    shipment["status"] = "DELIVERED"
    shipment["delivered_at"] = db.now_iso()
    touch(shipment)
    kit = db.kits.get(shipment["kit_id"])
    if kit:
        kit["status"] = "DELIVERED"
        touch(kit)
    return response.success_object(serialize(shipment), 200)


@bp.route("/pop/shipments/<shipment_id>/fail", methods=["POST"])
@require_roles("LogisticsCoordinator")
def fail(shipment_id):
    shipment = _get_shipment_or_404(shipment_id)
    if shipment["status"] != "SHIPPED":
        raise errors.err_invalid_state("Shipment is not in SHIPPED")
    shipment["status"] = "FAILED"
    touch(shipment)
    return response.success_object(serialize(shipment), 200)
