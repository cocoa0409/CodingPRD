"""Vehicle endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import errors
import model
import response
import serializers as ser
import validation as val
from middleware import get_auth, require_role

bp = Blueprint("vehicles", __name__)

VEHICLE_STATUSES = {"IN_SERVICE", "OUT_OF_SERVICE"}


@bp.route("/eld/vehicles", methods=["POST"])
def create_vehicle():
    _, role = get_auth()
    require_role(role, {"CarrierAdmin"})
    body = val.get_body()
    unit_number = val.require_str(body, "unit_number")
    vin = val.require_str(body, "vin")

    for r in db.vehicles.values():
        if r["unit_number"] == unit_number:
            raise errors.err(errors.ERR_DUPLICATE_UNIT, "unit_number already exists.")

    rec = {"unit_number": unit_number, "vin": vin, "status": "IN_SERVICE"}
    model.stamp_new(rec)
    db.vehicles[rec["id"]] = rec
    return response.object_response(ser.vehicle_view(rec), 201)


@bp.route("/eld/vehicles/<id>", methods=["GET"])
def get_vehicle(id):
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    rec = db.vehicles.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Vehicle not found.")
    return response.object_response(ser.vehicle_view(rec), 200)


@bp.route("/eld/vehicles/<id>", methods=["PATCH"])
def update_vehicle(id):
    _, role = get_auth()
    require_role(role, {"CarrierAdmin"})
    rec = db.vehicles.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Vehicle not found.")
    body = val.get_body()

    if "expected_vehicle_version" in body and body["expected_vehicle_version"] is not None:
        if body["expected_vehicle_version"] != rec["version"]:
            raise errors.err(errors.ERR_STALE_VERSION, "Vehicle version mismatch.")

    status = val.require_present(body, "status")
    val.enum_in(status, VEHICLE_STATUSES, "status")
    rec["status"] = status
    model.touch(rec)
    return response.object_response(ser.vehicle_view(rec), 200)
