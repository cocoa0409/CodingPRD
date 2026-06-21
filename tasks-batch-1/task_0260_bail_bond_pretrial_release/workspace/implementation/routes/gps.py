"""GpsDevice endpoints: register, fetch, list, assign, activate, clear-tamper, return."""
from flask import Blueprint

import db
from errors import err
from helpers import paginate, require_fields, require_str
from lookup import get_bond, get_bond_for_defendant, get_defendant, get_device_for_defendant
from middleware import (authenticate, get_json_body, parse_pagination,
                        require_role)
from response import array_response, object_response
from services import calculations as calc
from services import domain
from views import view, view_list

bp = Blueprint("gps", __name__)


@bp.route("/gps-devices", methods=["POST"])
def register_device():
    _, role = authenticate()
    require_role(role, {"BondsAgent"})
    body = get_json_body()
    require_fields(body, ["serial_number"])
    serial = require_str(body, "serial_number")

    for d in db.gps_devices.values():
        if d["serial_number"] == serial:
            raise err("ERR_DUPLICATE_SERIAL", "serial_number already registered.")

    rec = db.make_record({
        "serial_number": serial,
        "assigned_bond_id": None,
        "violation_count": 0,
        "status": "UNASSIGNED",
    })
    db.gps_devices[rec["id"]] = rec
    return object_response(view(rec), 201)


@bp.route("/gps-devices/<device_id>", methods=["GET"])
def fetch_device(device_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer", "RecoveryAgent"})
    d = db.gps_devices.get(device_id)
    if d is None:
        raise err("ERR_NOT_FOUND", "GPS device not found.")
    return object_response(view(d), 200)


@bp.route("/defendants/<defendant_id>/bonds/<bond_id>/gps/assign", methods=["POST"])
def assign_device(defendant_id, bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent"})
    bond = get_bond_for_defendant(defendant_id, bond_id)
    body = get_json_body()
    require_fields(body, ["device_id"])
    device_id = require_str(body, "device_id")

    device = db.gps_devices.get(device_id)
    if device is None:
        raise err("ERR_FK_NOT_FOUND", "device_id does not reference an existing device.")

    # State: device must be UNASSIGNED.
    if device["status"] != "UNASSIGNED":
        raise err("ERR_INVALID_STATE", "Device is not UNASSIGNED.")

    # Order must require GPS (priority 11).
    order = db.bail_orders.get(bond["bail_order_id"])
    if order is None or not order.get("gps_required", False):
        raise err("ERR_GPS_NOT_REQUIRED", "Bail order does not require GPS monitoring.")

    # Device occupancy: at most one non-returned device on the bond (priority 13).
    occupied = sum(1 for d in db.gps_devices.values()
                   if d.get("assigned_bond_id") == bond_id
                   and d["status"] in ("ASSIGNED", "ACTIVE", "TAMPER"))
    if occupied >= calc.DEVICE_CAPACITY:
        raise err("ERR_DEVICE_SLOT_OCCUPIED", "Bond monitoring slot already occupied.")

    device["status"] = "ASSIGNED"
    device["assigned_bond_id"] = bond_id
    db.touch(device)
    return object_response(view(device), 200)


@bp.route("/bonds/<bond_id>/gps-devices", methods=["GET"])
def list_bond_devices(bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer", "RecoveryAgent"})
    get_bond(bond_id)
    limit, offset = parse_pagination()
    records = [d for d in db.gps_devices.values() if d.get("assigned_bond_id") == bond_id]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


@bp.route("/defendants/<defendant_id>/gps/<device_id>/activate", methods=["POST"])
def activate_device(defendant_id, device_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent"})
    device = get_device_for_defendant(defendant_id, device_id)
    if device["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "Device is not ASSIGNED.")
    bond = db.bonds.get(device["assigned_bond_id"])
    if bond is None or bond["coverage_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Monitored bond is not ACTIVE.")
    device["status"] = "ACTIVE"
    db.touch(device)
    return object_response(view(device), 200)


@bp.route("/defendants/<defendant_id>/gps/<device_id>/clear-tamper", methods=["POST"])
def clear_tamper(defendant_id, device_id):
    _, role = authenticate()
    require_role(role, {"RecoveryAgent"})
    device = get_device_for_defendant(defendant_id, device_id)
    if device["status"] != "TAMPER":
        raise err("ERR_INVALID_STATE", "Device is not in TAMPER.")
    device["status"] = "ACTIVE"  # no counter reset
    db.touch(device)
    return object_response(view(device), 200)


@bp.route("/defendants/<defendant_id>/gps/<device_id>/return", methods=["POST"])
def return_device(defendant_id, device_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent"})
    device = get_device_for_defendant(defendant_id, device_id)
    if device["status"] not in ("ASSIGNED", "ACTIVE", "TAMPER"):
        raise err("ERR_INVALID_STATE", "Device cannot be returned from its current state.")
    device["status"] = "RETURNED"
    device["assigned_bond_id"] = None
    db.touch(device)
    return object_response(view(device), 200)
