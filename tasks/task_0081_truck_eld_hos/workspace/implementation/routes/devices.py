"""ELD device endpoints + binding lifecycle (PRD §3.1, §3.2)."""
from flask import Blueprint, request

import db
import errors
import model
import response
import serializers as ser
import validation as val
from middleware import get_auth, require_role
from paginate import paginate

bp = Blueprint("devices", __name__)

DEVICE_STATUSES = {"UNBOUND", "BOUND", "MALFUNCTION"}


@bp.route("/eld/devices", methods=["POST"])
def create_device():
    _, role = get_auth()
    require_role(role, {"CarrierAdmin"})
    body = val.get_body()
    serial_number = val.require_str(body, "serial_number")
    vehicle_id = val.require_str(body, "vehicle_id")

    # uniqueness before FK existence? PRD §2.10 puts ERR_REFERENCE_NOT_FOUND
    # (existence) ahead of business-constraint uniqueness; check FK first.
    if vehicle_id not in db.vehicles:
        raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "vehicle_id not found.")
    for r in db.devices.values():
        if r["serial_number"] == serial_number:
            raise errors.err(errors.ERR_DUPLICATE_SERIAL, "serial_number already exists.")

    rec = {
        "serial_number": serial_number,
        "vehicle_id": vehicle_id,
        "bound_driver_id": None,
        "status": "UNBOUND",
    }
    model.stamp_new(rec)
    db.devices[rec["id"]] = rec
    return response.object_response(ser.device_view(rec), 201)


@bp.route("/eld/devices/<id>", methods=["GET"])
def get_device(id):
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    rec = db.devices.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Device not found.")
    return response.object_response(ser.device_view(rec), 200)


@bp.route("/eld/devices", methods=["GET"])
def list_devices():
    _, role = get_auth()
    require_role(role, {"CarrierAdmin", "SafetyOfficer"})
    limit, offset = val.get_pagination()
    items = list(db.devices.values())
    vehicle_id = request.args.get("vehicle_id")
    bound_driver_id = request.args.get("bound_driver_id")
    status = request.args.get("status")
    if vehicle_id is not None:
        items = [r for r in items if r["vehicle_id"] == vehicle_id]
    if bound_driver_id is not None:
        items = [r for r in items if r["bound_driver_id"] == bound_driver_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return response.array_response([ser.device_view(r) for r in page], limit, offset, total)


@bp.route("/eld/devices/<id>/login", methods=["POST"])
def login(id):
    user_id, role = get_auth()
    require_role(role, {"Driver"})
    rec = db.devices.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Device not found.")

    driver = db.drivers.get(user_id)
    # state: device must be UNBOUND
    if rec["status"] != "UNBOUND":
        raise errors.err(errors.ERR_DEVICE_ALREADY_BOUND, "Device is not UNBOUND.")
    # vehicle in service
    vehicle = db.vehicles.get(rec["vehicle_id"])
    if vehicle is None or vehicle["status"] != "IN_SERVICE":
        raise errors.err(errors.ERR_VEHICLE_OUT_OF_SERVICE, "Vehicle is not IN_SERVICE.")
    # driver has no other BOUND device
    for d in db.devices.values():
        if d["status"] == "BOUND" and d["bound_driver_id"] == user_id:
            raise errors.err(errors.ERR_DRIVER_ALREADY_BOUND, "Driver already bound to a device.")
    # driver must exist and be ACTIVE
    if driver is None:
        raise errors.err(errors.ERR_UNAUTHORIZED, "Acting driver does not exist.")
    if driver["status"] != "ACTIVE":
        raise errors.err(errors.ERR_UNAUTHORIZED, "Driver is not ACTIVE.")

    rec["status"] = "BOUND"
    rec["bound_driver_id"] = user_id
    model.touch(rec)
    return response.object_response(ser.device_view(rec), 200)


@bp.route("/eld/devices/<id>/logout", methods=["POST"])
def logout(id):
    user_id, role = get_auth()
    require_role(role, {"Driver"})
    rec = db.devices.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Device not found.")

    # ownership: only the bound driver may log out
    if rec["status"] != "BOUND" or rec["bound_driver_id"] != user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED, "Not the bound driver.")
    # cannot logout while driving
    driver = db.drivers.get(user_id)
    if driver is not None and driver["current_duty_status"] == "DRIVING":
        raise errors.err(errors.ERR_CANNOT_LOGOUT_WHILE_DRIVING, "Cannot logout while driving.")

    rec["status"] = "UNBOUND"
    rec["bound_driver_id"] = None
    model.touch(rec)
    return response.object_response(ser.device_view(rec), 200)


@bp.route("/eld/devices/<id>/flag-malfunction", methods=["POST"])
def flag_malfunction(id):
    _, role = get_auth()
    require_role(role, {"CarrierAdmin"})
    rec = db.devices.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Device not found.")
    if rec["status"] != "BOUND":
        raise errors.err(errors.ERR_INVALID_STATE, "Device is not BOUND.")
    rec["status"] = "MALFUNCTION"
    model.touch(rec)
    return response.object_response(ser.device_view(rec), 200)


@bp.route("/eld/devices/<id>/clear-malfunction", methods=["POST"])
def clear_malfunction(id):
    _, role = get_auth()
    require_role(role, {"CarrierAdmin"})
    rec = db.devices.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Device not found.")
    if rec["status"] != "MALFUNCTION":
        raise errors.err(errors.ERR_INVALID_STATE, "Device is not in MALFUNCTION.")
    rec["status"] = "UNBOUND"
    rec["bound_driver_id"] = None
    model.touch(rec)
    return response.object_response(ser.device_view(rec), 200)
