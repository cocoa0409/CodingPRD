"""StorageAgreement lifecycle + MonitoringSubscription routes."""
from datetime import timedelta

from flask import Blueprint, request

import core
from core import (
    db, require, get_body, get_or_404, base_record, touch, success,
    list_response, req_str, req_int, req_enum, req_dt, check_owner, ApiError,
    now_clock,
)
from services import (
    ser_agreement, ser_monitoring, ser_service_order,
    storage_monthly_fee, release_unit_to_available, run_waitlist_promotion,
    TERMINAL_AGREEMENT,
)

bp = Blueprint("agreements", __name__)

MONITOR_TYPES = {"BATTERY_TENDER", "CLIMATE", "BOTH"}
AGREEMENT_STATUSES = {"PENDING", "IN_STORAGE", "CHECKED_OUT", "CLOSED", "CANCELLED"}


def _has_active_service(aid):
    return any(so["agreement_id"] == aid and so["status"] in ("IN_PROGRESS", "ON_HOLD")
               for so in db.service_orders.values())


def _overlaps(a_start, a_end, b_start, b_end):
    # half-open [start, end): overlap iff a_start < b_end and b_start < a_end
    return a_start < b_end and b_start < a_end


@bp.post("/storage-agreements")
def create_agreement():
    require("VaultManager")
    body = get_body()
    member_id = req_str(body, "member_id")
    vehicle_id = req_str(body, "vehicle_id")
    unit_id = req_str(body, "unit_id")
    move_in_at = req_dt(body, "move_in_at")
    planned_move_out_at = req_dt(body, "planned_move_out_at")
    expected_unit_version = req_int(body, "expected_unit_version")
    member = get_or_404(db.members, member_id)
    get_or_404(db.vehicles, vehicle_id)
    unit = get_or_404(db.units, unit_id)
    # Fiscal gate (§3.3).
    if member["billing_status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED", 402, "Member is suspended")
    # Overlap check against non-terminal agreements on this unit (§3.3).
    for a in db.agreements.values():
        if a["unit_id"] == unit_id and a["status"] not in TERMINAL_AGREEMENT:
            if _overlaps(move_in_at, planned_move_out_at, a["move_in_at"], a["planned_move_out_at"]):
                raise ApiError("ERR_UNIT_OVERLAP", 409, "Booking window overlaps an existing agreement")
    # Optimistic concurrency (§2.5).
    if expected_unit_version != unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION", 412, "Stale unit version")
    rec = base_record()
    rec.update({
        "member_id": member_id,
        "vehicle_id": vehicle_id,
        "unit_id": unit_id,
        "move_in_at": move_in_at,
        "planned_move_out_at": planned_move_out_at,
        "actual_move_out_at": None,
        "monthly_rate_cents": storage_monthly_fee(unit, member),
        "days_stored": None,
        "status": "PENDING",
    })
    db.agreements[rec["id"]] = rec
    # Recording the booking window bumps the unit version, leaves status unchanged.
    touch(unit)
    return success(ser_agreement(rec), status=201)


@bp.get("/storage-agreements/<aid>")
def get_agreement(aid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    rec = get_or_404(db.agreements, aid)
    return success(ser_agreement(rec))


@bp.get("/storage-agreements")
def list_agreements():
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    member_id = request.args.get("member_id")
    vehicle_id = request.args.get("vehicle_id")
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")
    items = [a for a in db.agreements.values()
             if (member_id is None or a["member_id"] == member_id)
             and (vehicle_id is None or a["vehicle_id"] == vehicle_id)
             and (unit_id is None or a["unit_id"] == unit_id)
             and (status is None or a["status"] == status)]
    return list_response(items, ser_agreement)


@bp.post("/storage-agreements/<aid>/move-in")
def move_in(aid):
    require("VaultManager")
    agr = get_or_404(db.agreements, aid)
    if agr["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not PENDING")
    unit = db.units.get(agr["unit_id"])
    if unit is None or unit["status"] not in ("AVAILABLE", "RESERVED"):
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", 409, "Assigned unit is not available")
    vehicle = db.vehicles.get(agr["vehicle_id"])
    if vehicle is None or vehicle["condition_status"] != "DOCUMENTED":
        raise ApiError("ERR_CROSS_ENTITY_STATE", 409, "Vehicle is not DOCUMENTED")
    unit["status"] = "OCCUPIED"
    touch(unit)
    agr["status"] = "IN_STORAGE"
    touch(agr)
    return success(ser_agreement(agr))


@bp.post("/storage-agreements/<aid>/check-out")
def check_out(aid):
    uid, role = require("Member", "ConciergeTech")
    agr = get_or_404(db.agreements, aid)
    check_owner(role, uid, agr["member_id"])
    if agr["status"] != "IN_STORAGE":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not IN_STORAGE")
    if _has_active_service(aid):
        raise ApiError("ERR_AGREEMENT_HAS_ACTIVE_SERVICE", 409, "Agreement has active service")
    agr["status"] = "CHECKED_OUT"
    touch(agr)
    return success(ser_agreement(agr))


@bp.post("/storage-agreements/<aid>/check-in")
def check_in(aid):
    uid, role = require("Member", "ConciergeTech")
    agr = get_or_404(db.agreements, aid)
    check_owner(role, uid, agr["member_id"])
    if agr["status"] != "CHECKED_OUT":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not CHECKED_OUT")
    agr["status"] = "IN_STORAGE"
    touch(agr)
    return success(ser_agreement(agr))


@bp.post("/storage-agreements/<aid>/terminate")
def terminate(aid):
    require("VaultManager")
    agr = get_or_404(db.agreements, aid)
    if agr["status"] not in ("IN_STORAGE", "CHECKED_OUT"):
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not in storage")
    if _has_active_service(aid):
        raise ApiError("ERR_AGREEMENT_HAS_ACTIVE_SERVICE", 409, "Agreement has active service")
    clock = now_clock()
    agr["actual_move_out_at"] = clock
    delta = clock - agr["move_in_at"]
    agr["days_stored"] = int(delta.total_seconds() // 86400)
    agr["status"] = "CLOSED"
    touch(agr)
    # Cascade 1: ACTIVE monitoring -> CANCELLED.
    for sub in db.monitorings.values():
        if sub["agreement_id"] == aid and sub["status"] == "ACTIVE":
            sub["status"] = "CANCELLED"
            touch(sub)
    # Cascade 2 + 3: release unit -> AVAILABLE, run promotion.
    unit = db.units.get(agr["unit_id"])
    if unit is not None and unit["status"] == "OCCUPIED":
        release_unit_to_available(unit)
    return success(ser_agreement(agr))


@bp.post("/storage-agreements/<aid>/cancel")
def cancel_agreement(aid):
    uid, role = require("Member", "VaultManager")
    agr = get_or_404(db.agreements, aid)
    check_owner(role, uid, agr["member_id"])
    if agr["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not PENDING")
    agr["status"] = "CANCELLED"
    touch(agr)
    # Release booking window; bump unit version. If the unit was RESERVED for
    # this member, free it and re-run promotion.
    unit = db.units.get(agr["unit_id"])
    if unit is not None:
        if unit["status"] == "RESERVED":
            unit["status"] = "AVAILABLE"
        touch(unit)
        run_waitlist_promotion(unit)
    return success(ser_agreement(agr))


# ---- MonitoringSubscription ----
@bp.post("/storage-agreements/<aid>/monitoring")
def add_monitoring(aid):
    require("ConciergeTech", "VaultManager")
    get_or_404(db.agreements, aid)
    body = get_body()
    monitor_type = req_enum(body, "monitor_type", MONITOR_TYPES)
    monthly_fee_cents = req_int(body, "monthly_fee_cents", minimum=0)
    rec = base_record()
    rec.update({
        "agreement_id": aid,
        "monitor_type": monitor_type,
        "monthly_fee_cents": monthly_fee_cents,
        "status": "ACTIVE",
        "last_battery_voltage": None,
    })
    db.monitorings[rec["id"]] = rec
    return success(ser_monitoring(rec), status=201)


@bp.get("/storage-agreements/<aid>/monitoring")
def list_monitoring(aid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    get_or_404(db.agreements, aid)
    subs = [s for s in db.monitorings.values() if s["agreement_id"] == aid]
    return list_response(subs, ser_monitoring)


@bp.get("/storage-agreements/<aid>/service-orders")
def list_agreement_service_orders(aid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    get_or_404(db.agreements, aid)
    orders = [o for o in db.service_orders.values() if o["agreement_id"] == aid]
    return list_response(orders, ser_service_order)


@bp.post("/monitoring/<sid>/record-reading")
def record_reading(sid):
    require("ConciergeTech")
    sub = get_or_404(db.monitorings, sid)
    body = get_body()
    from core import req_num
    battery_voltage = req_num(body, "battery_voltage")
    sub["last_battery_voltage"] = battery_voltage
    touch(sub)
    return success(ser_monitoring(sub))
