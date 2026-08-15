"""Access device endpoints (PRD 3.3)."""
from flask import Blueprint, request

import db
from errors import err_invalid_state, err_device_identity
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_string, require_enum, parse_pagination, paginate,
    require_ref, get_device, public_view,
)

bp = Blueprint("devices", __name__)

DEVICE_KINDS = {"ENTRY_GATE", "EXIT_GATE", "PAY_STATION"}


@bp.post("/ops/access-devices")
def create_device():
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    payload = body()
    facility = require_ref(payload, db.facilities, "facility_id")
    label = require_string(payload, "device_label")
    kind = require_enum(payload, "device_kind", DEVICE_KINDS)
    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "device_label": label,
        "device_kind": kind,
        "device_status": "OFFLINE",
        "device_mode": "STANDARD",
        "last_heartbeat_at": None,
    }
    db.stamp_new(ent)
    db.access_devices[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/access-devices/<access_device_id>")
def get_device_route(access_device_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_device(access_device_id)))


@bp.get("/ops/access-devices")
def list_devices():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.access_devices.values())
    facility_id = request.args.get("facility_id")
    device_status = request.args.get("device_status")
    if facility_id is not None:
        items = [d for d in items if d["facility_id"] == facility_id]
    if device_status is not None:
        items = [d for d in items if d["device_status"] == device_status]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(d) for d in page], limit, offset, total)


@bp.post("/ops/access-devices/<access_device_id>/heartbeat")
def heartbeat(access_device_id):
    actor = get_actor()
    require_roles(actor, ["GateDevice"])
    # identity binding: X-User-ID must equal the device id in the path (stage 3)
    if actor.user_id != access_device_id:
        raise err_device_identity()
    dev = get_device(access_device_id)
    if dev["device_status"] not in ("OFFLINE", "DEGRADED"):
        raise err_invalid_state("heartbeat requires OFFLINE or DEGRADED")
    dev["device_status"] = "ONLINE"
    dev["last_heartbeat_at"] = db.now_iso()
    db.touch(dev)
    return success_object(public_view(dev))


@bp.post("/ops/access-devices/<access_device_id>/report-fault")
def report_fault(access_device_id):
    actor = get_actor()
    require_roles(actor, ["GateDevice", "FacilityManager"])
    if actor.role == "GateDevice" and actor.user_id != access_device_id:
        raise err_device_identity()
    dev = get_device(access_device_id)
    payload = body()
    require_string(payload, "fault_description")
    if dev["device_status"] != "ONLINE":
        raise err_invalid_state("report-fault requires ONLINE")
    dev["device_status"] = "DEGRADED"
    db.touch(dev)
    return success_object(public_view(dev))


@bp.post("/ops/access-devices/<access_device_id>/decommission")
def decommission_device(access_device_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    dev = get_device(access_device_id)
    if dev["device_status"] == "DECOMMISSIONED":
        raise err_invalid_state("device already DECOMMISSIONED")
    dev["device_status"] = "DECOMMISSIONED"
    dev["device_mode"] = "STANDARD"
    db.touch(dev)
    return success_object(public_view(dev))
