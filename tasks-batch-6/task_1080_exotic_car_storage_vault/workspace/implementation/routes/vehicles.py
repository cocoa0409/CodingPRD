"""Vehicle, COI, and inspection-list routes."""
from flask import Blueprint, request

import core
from core import (
    db, require, get_body, get_or_404, base_record, touch, success,
    list_response, req_str, req_int, req_enum, req_dt, check_owner, ApiError,
    now_clock,
)
from services import (
    ser_vehicle, ser_coi, ser_inspection, vehicle_insurance_status,
    cancel_scheduled_deliveries_for_vehicle,
)

bp = Blueprint("vehicles", __name__)

FUEL_TYPES = {"ICE", "HYBRID", "EV"}


@bp.post("/vehicles")
def create_vehicle():
    uid, role = require("Member", "VaultManager")
    body = get_body()
    member_id = req_str(body, "member_id")
    make = req_str(body, "make")
    model = req_str(body, "model")
    model_year = req_int(body, "model_year")
    vin = req_str(body, "vin")
    fuel_type = req_enum(body, "fuel_type", FUEL_TYPES)
    declared_value_cents = req_int(body, "declared_value_cents", minimum=0)
    check_owner(role, uid, member_id)
    get_or_404(db.members, member_id)
    for v in db.vehicles.values():
        if v["vin"] == vin:
            raise ApiError("ERR_DUPLICATE", 409, "vin already registered")
    rec = base_record()
    rec.update({
        "member_id": member_id,
        "make": make,
        "model": model,
        "model_year": model_year,
        "vin": vin,
        "fuel_type": fuel_type,
        "declared_value_cents": declared_value_cents,
        "condition_status": "INTAKE_PENDING",
    })
    db.vehicles[rec["id"]] = rec
    return success(ser_vehicle(rec), status=201)


@bp.get("/vehicles/<vid>")
def get_vehicle(vid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    rec = get_or_404(db.vehicles, vid)
    return success(ser_vehicle(rec))


@bp.get("/vehicles/<vid>/coi")
def list_vehicle_coi(vid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    get_or_404(db.vehicles, vid)
    cois = [c for c in db.cois.values() if c["vehicle_id"] == vid]
    return list_response(cois, ser_coi)


@bp.get("/vehicles/<vid>/inspections")
def list_vehicle_inspections(vid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    get_or_404(db.vehicles, vid)
    ins = [i for i in db.inspections.values() if i["vehicle_id"] == vid]
    return list_response(ins, ser_inspection)


@bp.post("/vehicles/<vid>/coi")
def attach_coi(vid):
    uid, role = require("Member", "VaultManager")
    vehicle = get_or_404(db.vehicles, vid)
    check_owner(role, uid, vehicle["member_id"])
    body = get_body()
    policy_number = req_str(body, "policy_number")
    carrier = req_str(body, "carrier")
    coverage_amount_cents = req_int(body, "coverage_amount_cents", minimum=0)
    effective_at = req_dt(body, "effective_at")
    expiry_at = req_dt(body, "expiry_at")
    rec = base_record()
    rec.update({
        "vehicle_id": vid,
        "policy_number": policy_number,
        "carrier": carrier,
        "coverage_amount_cents": coverage_amount_cents,
        "effective_at": effective_at,
        "expiry_at": expiry_at,
        "status": "ACTIVE",
    })
    db.cois[rec["id"]] = rec
    # Vehicle insurance_status is computed on read; touch vehicle to reflect change.
    touch(vehicle)
    return success(ser_coi(rec), status=201)


@bp.post("/vehicles/<vid>/refresh-insurance")
def refresh_insurance(vid):
    require("VaultManager", "ConciergeTech")
    vehicle = get_or_404(db.vehicles, vid)
    clock = now_clock()
    before = vehicle_insurance_status(vid)
    changed = False
    for coi in db.cois.values():
        if coi["vehicle_id"] == vid and coi["status"] == "ACTIVE" and clock >= coi["expiry_at"]:
            coi["status"] = "EXPIRED"
            touch(coi)
            changed = True
    after = vehicle_insurance_status(vid)
    if changed:
        touch(vehicle)
    if before == "ACTIVE" and after == "LAPSED":
        cancel_scheduled_deliveries_for_vehicle(vid)
    return success(ser_vehicle(vehicle))


@bp.post("/coi/<cid>/revoke")
def revoke_coi(cid):
    require("VaultManager")
    coi = get_or_404(db.cois, cid)
    if coi["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "COI is not ACTIVE")
    vid = coi["vehicle_id"]
    before = vehicle_insurance_status(vid)
    coi["status"] = "REVOKED"
    touch(coi)
    vehicle = db.vehicles.get(vid)
    if vehicle is not None:
        touch(vehicle)
    after = vehicle_insurance_status(vid)
    if before == "ACTIVE" and after == "LAPSED":
        cancel_scheduled_deliveries_for_vehicle(vid)
    return success(ser_coi(coi))
