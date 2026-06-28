"""Warranty returns and RMA tickets (PRD §3.11)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import err
from middleware import authenticate, authorize
from response import success, paginated
from services import domain

bp = Blueprint("rma", __name__)

READ_ROLES = {"PlatformAdmin", "SupportEngineer", "ProjectManager"}


@bp.post("/rma-tickets")
def open_rma():
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    body = h.get_body()
    device_id = h.require_str(body, "device_id")
    contract_id = h.require_str(body, "contract_id")
    fault_code = h.require_enum(body, "fault_code", h.FAULT_CODES)
    resolution = h.optional_enum(body, "resolution", h.RMA_RESOLUTIONS, "RETURN_REPAIR")
    # referential integrity (priority 6): device + contract exist and belong to
    # the same project.
    device = db.devices.get(device_id)
    contract = db.contracts.get(contract_id)
    if device is None or contract is None:
        raise err("ERR_REFERENTIAL_INTEGRITY", "device_id or contract_id does not reference an existing row")
    device_project = domain.project_of_device(device)
    if device_project is None or device_project["id"] != contract["project_id"]:
        raise err("ERR_REFERENTIAL_INTEGRITY", "device and contract must belong to the same project")
    entity = {
        "device_id": device_id,
        "contract_id": contract_id,
        "fault_code": fault_code,
        "resolution": resolution,
        "status": "OPENED",
        "replacement_device_id": None,
    }
    db.stamp_create(entity)
    db.rma_tickets[entity["id"]] = entity
    return success(h.public(entity), status=201)


@bp.get("/rma-tickets/<rma_id>")
def get_rma(rma_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    entity = h.get_or_404(db.rma_tickets, rma_id)
    return success(h.public(entity))


@bp.get("/rma-tickets")
def list_rma():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = h.parse_pagination()
    device_id = request.args.get("device_id")
    replacement_device_id = request.args.get("replacement_device_id")
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    items = list(db.rma_tickets.values())
    if device_id is not None:
        items = [r for r in items if r["device_id"] == device_id]
    if replacement_device_id is not None:
        items = [r for r in items if r["replacement_device_id"] == replacement_device_id]
    if contract_id is not None:
        items = [r for r in items if r["contract_id"] == contract_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = h.sort_by_creation(items)
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(r) for r in page], limit, offset, total)


@bp.post("/rma-tickets/<rma_id>/authorize")
def authorize_rma(rma_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    rma = h.get_or_404(db.rma_tickets, rma_id)
    if rma["status"] != "OPENED":
        raise err("ERR_INVALID_STATE", "Only an OPENED RMA may be authorized")
    contract = db.contracts.get(rma["contract_id"])
    device = db.devices.get(rma["device_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise err("ERR_CONTRACT_NOT_ACTIVE", "Authorizing RMA requires an ACTIVE contract")
    if device is None or device["status"] != "FAULTED":
        raise err("ERR_DEVICE_NOT_FAULTED", "RMA device must be FAULTED")
    rma["status"] = "AUTHORIZED"
    if rma["resolution"] == "ADVANCE_REPLACE":
        # mint a new REGISTERED device on the same rack with the faulted
        # device's sku/category/rack_units (cross-aggregate cascade).
        new_dev = {
            "rack_id": device["rack_id"],
            "sku": device["sku"],
            "category": device["category"],
            "rack_units": device["rack_units"],
            "mgmt_ip": None,
            "firmware_version": None,
            "status": "REGISTERED",
            "is_controller": device["category"] == "CONTROLLER",
        }
        db.stamp_create(new_dev)
        db.devices[new_dev["id"]] = new_dev
        rma["replacement_device_id"] = new_dev["id"]
        rack = db.racks.get(device["rack_id"])
        if rack is not None:
            domain.recompute_rack_units(rack)
    db.touch(rma)
    return success(h.public(rma))


@bp.post("/rma-tickets/<rma_id>/deny")
def deny_rma(rma_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    rma = h.get_or_404(db.rma_tickets, rma_id)
    if rma["status"] != "OPENED":
        raise err("ERR_INVALID_STATE", "Only an OPENED RMA may be denied")
    rma["status"] = "DENIED"
    db.touch(rma)
    return success(h.public(rma))


@bp.post("/rma-tickets/<rma_id>/ship")
def ship_rma(rma_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    rma = h.get_or_404(db.rma_tickets, rma_id)
    if rma["status"] != "AUTHORIZED":
        raise err("ERR_INVALID_STATE", "Only an AUTHORIZED RMA may be shipped")
    rma["status"] = "SHIPPED"
    db.touch(rma)
    if rma["resolution"] == "RETURN_REPAIR":
        device = db.devices.get(rma["device_id"])
        # cascade: faulted device FAULTED -> RETIRED, releasing mgmt_ip + RU
        if device is not None and device["status"] == "FAULTED":
            domain.retire_device(device)
    return success(h.public(rma))


@bp.post("/rma-tickets/<rma_id>/close")
def close_rma(rma_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    rma = h.get_or_404(db.rma_tickets, rma_id)
    if rma["status"] != "SHIPPED":
        raise err("ERR_INVALID_STATE", "Only a SHIPPED RMA may be closed")
    rma["status"] = "CLOSED"
    db.touch(rma)
    return success(h.public(rma))
