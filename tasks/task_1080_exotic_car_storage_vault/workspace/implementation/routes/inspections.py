"""Inspection routes."""
from flask import Blueprint

import core
from core import (
    db, require, get_body, get_or_404, base_record, touch, success,
    req_str, req_enum, opt_bool, opt_str, ApiError,
)
from services import ser_inspection

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = {"INTAKE", "PERIODIC", "CHECKOUT"}


@bp.post("/inspections")
def create_inspection():
    require("ConciergeTech", "VaultManager")
    body = get_body()
    vehicle_id = req_str(body, "vehicle_id")
    inspection_type = req_enum(body, "inspection_type", INSPECTION_TYPES)
    get_or_404(db.vehicles, vehicle_id)
    rec = base_record()
    rec.update({
        "vehicle_id": vehicle_id,
        "inspection_type": inspection_type,
        "status": "SCHEDULED",
        "damage_noted": False,
        "findings": "",
    })
    db.inspections[rec["id"]] = rec
    return success(ser_inspection(rec), status=201)


@bp.get("/inspections/<iid>")
def get_inspection(iid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    rec = get_or_404(db.inspections, iid)
    return success(ser_inspection(rec))


@bp.post("/inspections/<iid>/pass")
def pass_inspection(iid):
    require("ConciergeTech", "VaultManager")
    ins = get_or_404(db.inspections, iid)
    body = get_body()
    damage_noted = opt_bool(body, "damage_noted", False)
    findings = opt_str(body, "findings", "")
    if ins["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Inspection is not SCHEDULED")
    ins["status"] = "PASSED"
    ins["damage_noted"] = damage_noted
    ins["findings"] = findings
    touch(ins)
    if ins["inspection_type"] == "INTAKE":
        vehicle = db.vehicles.get(ins["vehicle_id"])
        if vehicle is not None and vehicle["condition_status"] == "INTAKE_PENDING":
            vehicle["condition_status"] = "DOCUMENTED"
            touch(vehicle)
    return success(ser_inspection(ins))


@bp.post("/inspections/<iid>/fail")
def fail_inspection(iid):
    require("ConciergeTech", "VaultManager")
    ins = get_or_404(db.inspections, iid)
    body = get_body()
    damage_noted = opt_bool(body, "damage_noted", False)
    findings = opt_str(body, "findings", "")
    if ins["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Inspection is not SCHEDULED")
    ins["status"] = "FAILED"
    ins["damage_noted"] = damage_noted
    ins["findings"] = findings
    touch(ins)
    vehicle = db.vehicles.get(ins["vehicle_id"])
    if vehicle is not None:
        vehicle["condition_status"] = "DAMAGE_HOLD"
        touch(vehicle)
    return success(ser_inspection(ins))
