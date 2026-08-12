"""Unit and InspectionRecord endpoints."""
from flask import Blueprint, g, jsonify

import db
from auth import ALL_ROLES, require
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from scope import get_inspection_or_404, get_program_or_404, get_unit_or_404
from util import (
    body, bump, new_entity, ok_object, paginated, query_int, query_str,
    req_dt, req_enum, req_int, req_str, ser_inspection, ser_unit, opt_str,
)
import engine
from util import add_months
from datetime import timedelta

bp = Blueprint("units", __name__)

INSPECTION_READ = ["PlatformAdmin", "ProgramAdmin", "LeaseManager", "Inspector", "Household"]
RESULTS = {"PASSED", "FAILED", "NEEDS_REPAIR"}


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

@bp.post("/programs/<pid>/units")
@require(["ProgramAdmin"])
def create_unit(pid):
    program = get_program_or_404(pid)
    data = body()
    address = req_str(data, "address")
    bedrooms = req_int(data, "bedrooms")
    subsidy = req_int(data, "original_subsidy_cents")
    sale_price = req_int(data, "original_sale_price_cents")

    now = db.get_now()
    u = new_entity()
    u.update({
        "program_id": pid,
        "address": address,
        "bedrooms": bedrooms,
        "original_subsidy_cents": subsidy,
        "original_sale_price_cents": sale_price,
        "current_lease_id": None,
        "occupancy_status": "VACANT",
        "last_inspection_passed_at": None,
        "next_inspection_due_at": add_months(now, program["inspection_cycle_months"]),
        "maintenance_flag": "OK",
        "appraisal_value_cents": 0,
    })
    db.store.units[u["id"]] = u
    return jsonify(ok_object(ser_unit(u))), 201


@bp.get("/programs/<pid>/units")
@require(ALL_ROLES)
def list_units(pid):
    get_program_or_404(pid)
    items = [u for u in db.store.units.values() if u["program_id"] == pid]
    occupancy = query_str("occupancy_status")
    if occupancy:
        items = [u for u in items if u["occupancy_status"] == occupancy]
    flag = query_str("maintenance_flag")
    if flag:
        items = [u for u in items if u["maintenance_flag"] == flag]
    bedrooms = query_int("bedrooms")
    if bedrooms is not None:
        items = [u for u in items if u["bedrooms"] == bedrooms]
    return jsonify(paginated(items, ser_unit)), 200


@bp.get("/programs/<pid>/units/<uid>")
@require(ALL_ROLES)
def get_unit(pid, uid):
    return jsonify(ok_object(ser_unit(get_unit_or_404(pid, uid)))), 200


# ---------------------------------------------------------------------------
# InspectionRecords
# ---------------------------------------------------------------------------

@bp.post("/programs/<pid>/units/<uid>/inspections")
@require(["Inspector", "LeaseManager"])
def create_inspection(pid, uid):
    get_unit_or_404(pid, uid)
    data = body()
    scheduled_for = req_dt(data, "scheduled_for")

    r = new_entity()
    r.update({
        "unit_id": uid,
        "scheduled_for": scheduled_for,
        "completed_at": None,
        "inspector_user_id": g.user_id,
        "result": "PENDING",
        "findings": "",
        "follow_up_due_at": None,
        "linked_notice_id": None,
    })
    db.store.inspections[r["id"]] = r
    return jsonify(ok_object(ser_inspection(r))), 201


@bp.get("/programs/<pid>/units/<uid>/inspections")
@require(INSPECTION_READ)
def list_inspections(pid, uid):
    get_unit_or_404(pid, uid)
    items = [i for i in db.store.inspections.values() if i["unit_id"] == uid]
    result = query_str("result")
    if result:
        items = [i for i in items if i["result"] == result]
    return jsonify(paginated(items, ser_inspection)), 200


@bp.get("/programs/<pid>/units/<uid>/inspections/<iid>")
@require(INSPECTION_READ)
def get_inspection(pid, uid, iid):
    get_unit_or_404(pid, uid)
    return jsonify(ok_object(ser_inspection(get_inspection_or_404(pid, uid, iid)))), 200


@bp.post("/programs/<pid>/units/<uid>/inspections/<iid>/record-result")
@require(["Inspector"])
def record_inspection_result(pid, uid, iid):
    program = get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    record = get_inspection_or_404(pid, uid, iid)
    if record["result"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PENDING inspection can have its result recorded")
    data = body()
    result = req_enum(data, "result", RESULTS)
    findings = opt_str(data, "findings", "")

    now = db.get_now()
    record["result"] = result
    record["completed_at"] = now
    if findings:
        record["findings"] = findings
    bump(record)

    if result == "PASSED":
        unit["last_inspection_passed_at"] = now
        unit["next_inspection_due_at"] = add_months(now, program["inspection_cycle_months"])
        unit["maintenance_flag"] = "OK"
        bump(unit)
    elif result == "NEEDS_REPAIR":
        unit["maintenance_flag"] = "NEEDS_REPAIR"
        bump(unit)
        record["follow_up_due_at"] = now + timedelta(days=30)
    elif result == "FAILED":
        unit["maintenance_flag"] = "UNSAFE"
        bump(unit)
        lease_id = unit["current_lease_id"]
        lease = db.store.leases.get(lease_id) if lease_id else None
        if lease is not None and lease["status"] in ("ACTIVE", "IN_DEFAULT", "CURE_PERIOD"):
            notice = engine.issue_default_notice(
                program, unit, lease, "MAINTENANCE", 0, g.user_id, now)
            record["linked_notice_id"] = notice["id"]

    return jsonify(ok_object(ser_inspection(record))), 200
