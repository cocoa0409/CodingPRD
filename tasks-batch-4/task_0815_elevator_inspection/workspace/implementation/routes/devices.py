from flask import Blueprint, request

import errors
from auth import require
from common import (
    get_body,
    lookup,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
)
from constants import DEVICE_CATEGORIES, REGISTRATION_FEE_CENTS, RISK_CLASS
from envelope import array_response, object_response
from services.logic import serialize_device
from store import base_fields, db, touch

bp = Blueprint("devices", __name__)


@bp.route("/devices", methods=["POST"])
@require("Registrar")
def create_device():
    body = get_body()
    owner_id = require_string(body, "owner_id")
    category = require_enum(body, "category", DEVICE_CATEGORIES)
    location_description = require_string(body, "location_description")
    install_period = require_int(body, "install_period")
    # FK existence (priority 4)
    lookup(db.owners, owner_id, "ERR_OWNER_NOT_FOUND")

    device = base_fields()
    device.update({
        "owner_id": owner_id,
        "category": category,
        "location_description": location_description,
        "install_period": install_period,
        "risk_class": RISK_CLASS[category],
        "status": "REGISTERED",
        "next_inspection_due_period": None,
        "accident_risk_score": 0,
        "_registration_fee_id": None,
    })
    db.devices[device["id"]] = device

    # Auto-create the REGISTRATION fee invoice (PENDING, due at install_period).
    fee = base_fields()
    fee.update({
        "device_id": device["id"],
        "type": "REGISTRATION",
        "amount_cents": REGISTRATION_FEE_CENTS,
        "due_period": install_period,
        "paid_period": None,
        "status": "PENDING",
    })
    db.fee_invoices[fee["id"]] = fee
    device["_registration_fee_id"] = fee["id"]

    return object_response(serialize_device(device), 201)


@bp.route("/devices/<device_id>", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def get_device(device_id):
    device = lookup(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")
    return object_response(serialize_device(device), 200)


@bp.route("/devices", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def list_devices():
    limit, offset = parse_pagination()
    owner_id = request.args.get("owner_id")
    status = request.args.get("status")
    category = request.args.get("category")
    items = list(db.devices.values())
    if owner_id is not None:
        items = [d for d in items if d["owner_id"] == owner_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if category is not None:
        items = [d for d in items if d["category"] == category]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_device(d) for d in page], limit, offset, total)


@bp.route("/devices/<device_id>/activate", methods=["POST"])
@require("Registrar")
def activate_device(device_id):
    device = lookup(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")
    if device["status"] != "REGISTERED":
        raise errors.ApiError("ERR_DEVICE_NOT_REGISTERED", 409,
                              "Device is not in REGISTERED status.")
    reg_fee = db.fee_invoices.get(device.get("_registration_fee_id"))
    if reg_fee is None or reg_fee["status"] != "PAID":
        raise errors.ApiError("ERR_REGISTRATION_FEE_UNPAID", 402,
                              "The device's REGISTRATION fee invoice is not paid.")
    device["status"] = "ACTIVE"
    touch(device)
    return object_response(serialize_device(device), 200)


@bp.route("/devices/<device_id>/decommission", methods=["POST"])
@require("Registrar", "SafetyAdministrator")
def decommission_device(device_id):
    device = lookup(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")
    if device["status"] == "DECOMMISSIONED":
        raise errors.ApiError("ERR_DEVICE_ALREADY_DECOMMISSIONED", 409,
                              "Device is already decommissioned.")
    device["status"] = "DECOMMISSIONED"
    touch(device)
    # Cascade: cancel SCHEDULED/ASSIGNED inspections for this device.
    for insp in db.inspections.values():
        if insp["device_id"] == device_id and insp["status"] in ("SCHEDULED", "ASSIGNED"):
            insp["status"] = "CANCELLED"
            touch(insp)
    return object_response(serialize_device(device), 200)
