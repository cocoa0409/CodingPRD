"""Device / DeviceCommand routes (PRD 3.6)."""
from flask import Blueprint

import db
import lookups
from errors import err
from middleware import authenticate, require_role
from response import success, list_success
from serialize import public
from timeutil import iso_now, parse_iso
from validate import get_body, require_str, parse_pagination, paginate

bp = Blueprint("devices", __name__)

COMMAND_TYPES = {"STARTER_DISABLE", "STARTER_ENABLE", "LOCATE"}


def _sorted_public(entities):
    rows = sorted(entities, key=lambda e: e["_seq"])
    return [public(e) for e in rows]


@bp.route("/atl/devices", methods=["POST"])
def create_device():
    _, role = authenticate()
    require_role(role, {"LoanServicer"})
    body = get_body()

    vehicle_id = require_str(body, "vehicle_id")
    lookups.get_or_404(db.vehicles, vehicle_id)
    serial_number = require_str(body, "serial_number")

    # vehicle_id unique across devices; serial_number unique (PRD 3.6).
    for d in db.devices.values():
        if d["vehicle_id"] == vehicle_id:
            raise err("ERR_INVALID_STATE", "vehicle already has a device")
        if d["serial_number"] == serial_number:
            raise err("ERR_INVALID_STATE", "serial_number already registered")

    device = db.common_fields(with_version=True)
    device.update({
        "vehicle_id": vehicle_id,
        "serial_number": serial_number,
        "starter_state": "ENABLED",
        "active_disable_count": 0,
    })
    db.devices[device["id"]] = device
    return success(public(device), status=201)


@bp.route("/atl/devices/<device_id>", methods=["GET"])
def get_device(device_id):
    _, role = authenticate()
    require_role(role, {"LoanServicer", "RecoveryManager", "ComplianceAdmin"})
    device = lookups.get_or_404(db.devices, device_id)
    return success(public(device), status=200)


def _overlaps_closed(a_start, a_end, b_start, b_end):
    """Closed [start, end] overlap: adjacency at an endpoint DOES count as overlap."""
    return a_start <= b_end and b_start <= a_end


@bp.route("/atl/devices/<device_id>/commands", methods=["POST"])
def issue_command(device_id):
    _, role = authenticate()
    require_role(role, {"LoanServicer"})
    device = lookups.get_or_404(db.devices, device_id)
    body = get_body()

    command_type = require_str(body, "command_type")
    if command_type not in COMMAND_TYPES:
        raise err("ERR_INVALID_REQUEST", "command_type must be one of %s" % sorted(COMMAND_TYPES))
    effective_start = require_str(body, "effective_start")
    effective_end = require_str(body, "effective_end")

    es = parse_iso(effective_start)
    ee = parse_iso(effective_end)

    # Range check (PRD 2.6 step 6): effective_end at or after effective_start.
    if not (ee >= es):
        raise err("ERR_VALIDATION_RANGE", "effective_end must be >= effective_start")

    if command_type == "STARTER_DISABLE":
        # State legality (priority 6): device must be ENABLED (PRD 3.6).
        if device["starter_state"] != "ENABLED":
            raise err("ERR_INVALID_STATE", "device not in ENABLED")
        # Cross-entity guard (priority 10): vehicle's active loan must be
        # DELINQUENT or DEFAULT.
        active_loan = lookups.active_loan_for_vehicle(device["vehicle_id"])
        if active_loan is None or active_loan["delinquency_status"] not in ("DELINQUENT", "DEFAULT"):
            raise err("ERR_DEVICE_LOAN_NOT_DELINQUENT", "vehicle loan not delinquent")
        # Window-overlap guard (priority 15): closed-interval overlap with an
        # existing ISSUED STARTER_DISABLE window on the same device.
        for cmd in db.device_commands.values():
            if (cmd["device_id"] == device_id and cmd["command_type"] == "STARTER_DISABLE"
                    and cmd["status"] == "ISSUED"):
                cs = parse_iso(cmd["effective_start"])
                ce = parse_iso(cmd["effective_end"])
                if _overlaps_closed(es, ee, cs, ce):
                    raise err("ERR_COMMAND_WINDOW_OVERLAP", "command window overlaps an existing ISSUED disable")
        cmd = _record_command(device, command_type, es, ee)
        device["starter_state"] = "DISABLED"
        device["active_disable_count"] += 1
        db.touch(device)
        return success(public(cmd), status=201)

    if command_type == "STARTER_ENABLE":
        # State legality (priority 6): device must be DISABLED (PRD 3.6).
        if device["starter_state"] != "DISABLED":
            raise err("ERR_INVALID_STATE", "device not in DISABLED")
        cmd = _record_command(device, command_type, es, ee)
        device["starter_state"] = "ENABLED"
        device["active_disable_count"] = max(0, device["active_disable_count"] - 1)
        db.touch(device)
        return success(public(cmd), status=201)

    # LOCATE: no state change, no guards beyond range (PRD 3.6).
    cmd = _record_command(device, command_type, es, ee)
    return success(public(cmd), status=201)


def _record_command(device, command_type, es, ee):
    cmd = db.common_fields(with_version=True)
    cmd.update({
        "device_id": device["id"],
        "command_type": command_type,
        "effective_start": iso_now(es),
        "effective_end": iso_now(ee),
        "status": "ISSUED",
    })
    db.device_commands[cmd["id"]] = cmd
    return cmd


@bp.route("/atl/devices/<device_id>/commands", methods=["GET"])
def list_commands(device_id):
    _, role = authenticate()
    require_role(role, {"LoanServicer", "RecoveryManager", "ComplianceAdmin"})
    lookups.get_or_404(db.devices, device_id)
    limit, offset = parse_pagination()
    rows = [c for c in db.device_commands.values() if c["device_id"] == device_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))
