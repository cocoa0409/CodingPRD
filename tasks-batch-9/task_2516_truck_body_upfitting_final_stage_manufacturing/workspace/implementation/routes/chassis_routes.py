"""Incoming vehicle custody: receipt, inspection, quarantine and return
(PRD section 3.2 / 3.3)."""

from flask import Blueprint

import db
import middleware
import response
import validation as v
from errors import ApiError
from services import cascade, lookup

chassis_bp = Blueprint("chassis", __name__, url_prefix="/upfit")


@chassis_bp.route("/chassis", methods=["POST"])
def receive_chassis():
    middleware.require(middleware.ROLE_PLANT_ADMIN)
    payload = v.body()
    vin = v.req_str(payload, "vin", min_len=None, exact_len=17)
    chassis_model_id = v.req_str(payload, "chassis_model_id")
    ownership = v.opt_enum(payload, "ownership", v.CHASSIS_OWNERSHIP, default="POOL_STOCK")
    availability_date = v.req_date(payload, "availability_date")

    lookup.chassis_model(chassis_model_id)

    for existing in db.chassis_units.values():
        if existing["vin"] == vin:
            raise ApiError("ERR_DUPLICATE_VIN", "VIN '%s' is already on record." % vin)

    row = db.insert(
        db.chassis_units,
        {
            "vin": vin,
            "chassis_model_id": chassis_model_id,
            "ownership": ownership,
            "status": "RECEIVED",
            "measured_front_axle_weight_lb": None,
            "measured_rear_axle_weight_lb": None,
            "availability_date": availability_date,
            "allocated_upfit_order_id": None,
            "quarantine_reason": None,
        },
    )
    return response.object_response(db.serialize(row), 201)


@chassis_bp.route("/chassis/<chassis_id>/inspect", methods=["POST"])
def inspect_chassis(chassis_id):
    middleware.require(middleware.ROLE_INSTALL_TECHNICIAN)
    payload = v.body()
    front = v.req_int(payload, "measured_front_axle_weight_lb", minimum=0)
    rear = v.req_int(payload, "measured_rear_axle_weight_lb", minimum=0)

    unit = lookup.chassis(chassis_id)
    if unit["status"] not in ("RECEIVED", "QUARANTINED"):
        raise ApiError(
            "ERR_CHASSIS_INVALID_STATE",
            "Inspection accepts a unit at RECEIVED or QUARANTINED; this one is %s."
            % unit["status"],
        )
    unit["measured_front_axle_weight_lb"] = front
    unit["measured_rear_axle_weight_lb"] = rear
    unit["quarantine_reason"] = None
    unit["status"] = "INSPECTED"
    db.touch(unit)
    return response.object_response(db.serialize(unit), 200)


@chassis_bp.route("/chassis/<chassis_id>/quarantine", methods=["POST"])
def quarantine_chassis(chassis_id):
    middleware.require(middleware.ROLE_PLANT_ADMIN)
    payload = v.body()
    reason = v.req_str(payload, "quarantine_reason")

    unit = lookup.chassis(chassis_id)
    if unit["status"] not in ("RECEIVED", "INSPECTED"):
        raise ApiError(
            "ERR_CHASSIS_INVALID_STATE",
            "Quarantine accepts a unit at RECEIVED or INSPECTED; this one is %s." % unit["status"],
        )
    unit["status"] = "QUARANTINED"
    unit["quarantine_reason"] = reason
    db.touch(unit)
    return response.object_response(db.serialize(unit), 200)


@chassis_bp.route("/chassis/<chassis_id>/return", methods=["POST"])
def return_chassis(chassis_id):
    middleware.require(middleware.ROLE_PLANT_ADMIN)
    payload = v.body()
    v.req_str(payload, "reason")

    unit = lookup.chassis(chassis_id)
    if unit["status"] not in ("INSPECTED", "ALLOCATED", "IN_UPFIT"):
        raise ApiError(
            "ERR_CHASSIS_INVALID_STATE",
            "Return accepts a unit at INSPECTED, ALLOCATED or IN_UPFIT; this one is %s."
            % unit["status"],
        )
    unit["status"] = "RETURNED"
    db.touch(unit)
    cascade.chassis_return_cascade(unit)
    return response.object_response(db.serialize(unit), 200)


@chassis_bp.route("/chassis/<chassis_id>", methods=["GET"])
def get_chassis(chassis_id):
    middleware.require(*middleware.STAFF_ROLES)
    return response.object_response(db.serialize(lookup.chassis(chassis_id)), 200)


@chassis_bp.route("/chassis", methods=["GET"])
def list_chassis():
    middleware.require(*middleware.STAFF_ROLES)
    chassis_model_id = v.filter_str("chassis_model_id")
    allocated_upfit_order_id = v.filter_str("allocated_upfit_order_id")
    ownership = v.filter_enum("ownership", v.CHASSIS_OWNERSHIP)
    status = v.filter_enum("status", v.CHASSIS_STATUS)
    rows = list(db.chassis_units.values())
    if chassis_model_id is not None:
        rows = [r for r in rows if r["chassis_model_id"] == chassis_model_id]
    if allocated_upfit_order_id is not None:
        rows = [r for r in rows if r["allocated_upfit_order_id"] == allocated_upfit_order_id]
    if ownership is not None:
        rows = [r for r in rows if r["ownership"] == ownership]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(rows)
