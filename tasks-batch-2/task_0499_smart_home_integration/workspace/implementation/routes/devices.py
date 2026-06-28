"""Devices, provisioning, commissioning, and firmware (PRD §3.5, §3.10)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import err
from middleware import authenticate, authorize
from response import success, paginated
from services import calc, domain

bp = Blueprint("devices", __name__)

READ_ROLES = {"PlatformAdmin", "SystemsDesigner", "ProjectManager", "SupportEngineer", "LowVoltageTech", "Client"}
FIRMWARE_READ_ROLES = {"PlatformAdmin", "SupportEngineer", "LowVoltageTech", "ProjectManager"}

NON_TERMINAL_PROJECT_FOR_PROVISION = {"PROVISIONING", "SCHEDULED", "INSTALLING", "COMMISSIONED", "ACTIVE"}


def _device_has_open_rma(device_id):
    for r in db.rma_tickets.values():
        if r["device_id"] == device_id and r["status"] in ("OPENED", "AUTHORIZED", "SHIPPED"):
            return True
    return False


# ---------------------------------------------------------------------------
# Register device (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.post("/devices")
def create_device():
    _, role = authenticate()
    authorize(role, {"LowVoltageTech", "ProjectManager"})
    body = h.get_body()
    rack_id = h.require_str(body, "rack_id")
    sku = h.require_str(body, "sku")
    category = h.require_enum(body, "category", h.DEVICE_CATEGORIES)
    rack_units = h.optional_int(body, "rack_units", 1, minimum=0)
    # FK referential integrity (priority 6): rack_id must be a real rack
    if rack_id not in db.racks:
        raise err("ERR_REFERENTIAL_INTEGRITY", "rack_id does not reference an existing rack")
    entity = {
        "rack_id": rack_id,
        "sku": sku,
        "category": category,
        "rack_units": rack_units,
        "mgmt_ip": None,
        "firmware_version": None,
        "status": "REGISTERED",
        "is_controller": category == "CONTROLLER",
    }
    db.stamp_create(entity)
    db.devices[entity["id"]] = entity
    rack = db.racks[rack_id]
    domain.recompute_rack_units(rack)
    return success(h.public(entity), status=201)


@bp.get("/devices/<device_id>")
def get_device(device_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    entity = h.get_or_404(db.devices, device_id)
    return success(h.public(entity))


@bp.get("/devices")
def list_devices():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = h.parse_pagination()
    rack_id = request.args.get("rack_id")
    status = request.args.get("status")
    items = list(db.devices.values())
    if rack_id is not None:
        items = [d for d in items if d["rack_id"] == rack_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = h.sort_by_creation(items)
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(d) for d in page], limit, offset, total)


@bp.post("/devices/<device_id>/provision")
def provision_device(device_id):
    _, role = authenticate()
    authorize(role, {"LowVoltageTech"})
    device = h.get_or_404(db.devices, device_id)
    if device["status"] != "REGISTERED":
        raise err("ERR_INVALID_STATE", "Device is not REGISTERED")
    rack = db.racks.get(device["rack_id"])
    project = domain.project_of_device(device)
    if project is None or project["status"] not in NON_TERMINAL_PROJECT_FOR_PROVISION:
        raise err("ERR_INVALID_STATE", "Project is not in PROVISIONING or later non-terminal state")
    # capacity (priority 13): rack RU then IP pool
    if rack["rack_units_used"] + device["rack_units"] > rack["rack_units_total"]:
        raise err("ERR_RACK_CAPACITY_EXCEEDED", "Provisioning would exceed rack capacity")
    taken = [
        d["mgmt_ip"] for d in domain.devices_for_rack(rack["id"])
        if d["status"] != "RETIRED" and d.get("mgmt_ip")
    ]
    ip = calc.allocate_mgmt_ip(rack["subnet_cidr"], taken)
    if ip is None:
        raise err("ERR_IP_POOL_EXHAUSTED", "No free management address in subnet")
    device["mgmt_ip"] = ip
    device["status"] = "PROVISIONED"
    db.touch(device)
    domain.recompute_rack_units(rack)
    domain.recompute_project_counters(project)
    return success(h.public(device))


@bp.post("/devices/<device_id>/bring-online")
def bring_online(device_id):
    _, role = authenticate()
    authorize(role, {"LowVoltageTech"})
    device = h.get_or_404(db.devices, device_id)
    if device["status"] not in ("PROVISIONED", "FAULTED"):
        raise err("ERR_INVALID_STATE", "Device is not PROVISIONED or FAULTED")
    if device.get("firmware_version") is None:
        raise err("ERR_FIRMWARE_REQUIRED", "Device requires applied firmware before going online")
    device["status"] = "ONLINE"
    db.touch(device)
    project = domain.project_of_device(device)
    if project is not None:
        domain.recompute_project_counters(project)
    return success(h.public(device))


@bp.post("/devices/<device_id>/mark-faulted")
def mark_faulted(device_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    device = h.get_or_404(db.devices, device_id)
    if device["status"] != "ONLINE":
        raise err("ERR_INVALID_STATE", "Only an ONLINE device may be marked FAULTED")
    device["status"] = "FAULTED"
    db.touch(device)
    domain.dedeploy_scenes_for_device(device)
    project = domain.project_of_device(device)
    if project is not None:
        domain.recompute_project_counters(project)
    return success(h.public(device))


@bp.post("/devices/<device_id>/retire")
def retire_device(device_id):
    _, role = authenticate()
    authorize(role, {"LowVoltageTech"})
    device = h.get_or_404(db.devices, device_id)
    if device["status"] not in ("REGISTERED", "PROVISIONED", "ONLINE"):
        raise err("ERR_INVALID_STATE", "Device cannot be retired from its current state")
    if _device_has_open_rma(device_id):
        raise err("ERR_DEVICE_HAS_OPEN_RMA", "Device is referenced by an open RMA")
    domain.retire_device(device)
    return success(h.public(device))


# ---------------------------------------------------------------------------
# Firmware updates (PRD §3.10)
# ---------------------------------------------------------------------------
def _firmware_for_device(device_id):
    return [f for f in db.firmware_updates.values() if f["device_id"] == device_id]


@bp.post("/devices/<device_id>/firmware-updates")
def stage_firmware(device_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    device = h.get_or_404(db.devices, device_id)
    body = h.get_body()
    target_version = h.require_str(body, "target_version")
    entity = {
        "device_id": device_id,
        "target_version": target_version,
        "status": "STAGED",
        "prior_version": None,
    }
    db.stamp_create(entity)
    db.firmware_updates[entity["id"]] = entity
    return success(h.public(entity), status=201)


@bp.get("/devices/<device_id>/firmware-updates")
def list_firmware(device_id):
    _, role = authenticate()
    authorize(role, FIRMWARE_READ_ROLES)
    h.get_or_404(db.devices, device_id)
    limit, offset = h.parse_pagination()
    status = request.args.get("status")
    items = _firmware_for_device(device_id)
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = h.sort_by_creation(items)
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(f) for f in page], limit, offset, total)


def _firmware_in_device(device_id, update_id):
    device = h.get_or_404(db.devices, device_id)
    fw = db.firmware_updates.get(update_id)
    if fw is None or fw["device_id"] != device_id:
        raise err("ERR_NOT_FOUND", "Firmware update not found for device")
    return device, fw


@bp.post("/devices/<device_id>/firmware-updates/<update_id>/apply")
def apply_firmware(device_id, update_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    device, fw = _firmware_in_device(device_id, update_id)
    if fw["status"] != "STAGED":
        raise err("ERR_INVALID_STATE", "Firmware update is not STAGED")
    if device["status"] not in ("PROVISIONED", "ONLINE", "FAULTED"):
        raise err("ERR_INVALID_STATE", "Device must be PROVISIONED, ONLINE, or FAULTED")
    if not calc.semver_gt(fw["target_version"], device.get("firmware_version")):
        raise err("ERR_FIRMWARE_NOT_NEWER", "target_version must be strictly newer")
    fw["prior_version"] = device.get("firmware_version")
    fw["status"] = "APPLIED"
    db.touch(fw)
    device["firmware_version"] = fw["target_version"]
    db.touch(device)
    return success(h.public(fw))


@bp.post("/devices/<device_id>/firmware-updates/<update_id>/fail")
def fail_firmware(device_id, update_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    device, fw = _firmware_in_device(device_id, update_id)
    if fw["status"] != "STAGED":
        raise err("ERR_INVALID_STATE", "Firmware update is not STAGED")
    fw["status"] = "FAILED"
    db.touch(fw)
    return success(h.public(fw))


@bp.post("/devices/<device_id>/firmware-updates/<update_id>/rollback")
def rollback_firmware(device_id, update_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    device, fw = _firmware_in_device(device_id, update_id)
    if fw["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Firmware update is not APPLIED")
    # must be the most recently APPLIED firmware update for the device
    applied = [f for f in _firmware_for_device(device_id) if f["status"] == "APPLIED"]
    latest = max(applied, key=lambda f: f["_seq"]) if applied else None
    if latest is None or latest["id"] != update_id:
        raise err("ERR_NOT_LATEST_FIRMWARE", "Not the most recently applied firmware update")
    fw["status"] = "ROLLED_BACK"
    db.touch(fw)
    device["firmware_version"] = fw["prior_version"]
    db.touch(device)
    return success(h.public(fw))
