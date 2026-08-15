"""EquipmentUnit and EquipmentAssignment endpoints (PRD §3.4)."""
from flask import Blueprint, request

import errors
import services
from db import all_of, get, new_resource, pub, save, touch
from middleware import list_response, req_datetime, req_enum, req_field, req_str, require_roles
from response import get_body, ok

bp = Blueprint("equipment", __name__)

EQUIPMENT_TYPES = ("SHIP_CRANE", "RTG", "FORKLIFT", "TRACTOR")
READ_ROLES = ("StevedoreAdmin", "StevedoreSuperintendent", "LaborHallDispatcher", "GangForeman")


# --- EquipmentUnit ---------------------------------------------------------

@bp.post("/api/equipment-units")
def create_unit():
    require_roles("StevedoreAdmin")
    body = get_body()
    unit_code = req_str(body, "unit_code")
    equipment_type = req_enum(body, "equipment_type", EQUIPMENT_TYPES)
    for u in all_of("equipment_units"):
        if u["unit_code"] == unit_code:
            raise errors.validation("unit_code already exists")
    rec = new_resource("equipment_units")
    rec.update({
        "unit_code": unit_code,
        "equipment_type": equipment_type,
        "status": "AVAILABLE",
        "total_breakdowns": 0,
    })
    save("equipment_units", rec)
    return ok(pub(rec), 201)


@bp.get("/api/equipment-units")
def list_units():
    require_roles(*READ_ROLES)
    return list_response("equipment_units", {
        "equipment_type": request.args.get("equipment_type"),
        "status": request.args.get("status"),
    })


def _get_unit(uid):
    u = get("equipment_units", uid)
    if u is None:
        raise errors.not_found("Equipment unit not found")
    return u


@bp.get("/api/equipment-units/<uid>")
def get_unit(uid):
    require_roles(*READ_ROLES)
    return ok(pub(_get_unit(uid)))


@bp.post("/api/equipment-units/<uid>/repair-complete")
def repair_complete(uid):
    require_roles("StevedoreAdmin")
    u = _get_unit(uid)
    if u["status"] != "DOWN":
        raise errors.invalid_state("Only a DOWN unit can complete repair")
    u["status"] = "AVAILABLE"
    touch(u)
    return ok(pub(u))


# --- EquipmentAssignment ----------------------------------------------------

@bp.post("/api/equipment-assignments")
def create_equipment_assignment():
    require_roles("StevedoreSuperintendent")
    body = get_body()
    # existence (3), left to right
    gang_order_id = req_field(body, "gang_order_id")
    gang = get("gang_orders", gang_order_id)
    if gang is None:
        raise errors.not_found("Gang order not found")
    equipment_unit_id = req_field(body, "equipment_unit_id")
    unit = get("equipment_units", equipment_unit_id)
    if unit is None:
        raise errors.not_found("Equipment unit not found")
    # schema (4)
    start_raw, start = req_datetime(body, "window_start_utc")
    end_raw, end = req_datetime(body, "window_end_utc")
    if end <= start:
        raise errors.validation("window_end_utc must be later than window_start_utc")
    # temporal (9): 30-minute buffered-window rule against RESERVED/ACTIVE bookings
    for ea in services.eas_of_unit(unit["id"]):
        if ea["status"] in ("RESERVED", "ACTIVE"):
            if services.windows_conflict(start, end, ea["_ws"], ea["_we"]):
                raise errors.equipment_window_conflict()
    # capacity (10): a DOWN unit cannot be booked at all
    if unit["status"] == "DOWN":
        raise errors.equipment_unavailable()
    rec = new_resource("equipment_assignments")
    rec.update({
        "gang_order_id": gang_order_id,
        "equipment_unit_id": equipment_unit_id,
        "window_start_utc": start_raw,
        "window_end_utc": end_raw,
        "status": "RESERVED",
        "replaced_by_assignment_id": None,
        "_ws": start,
        "_we": end,
    })
    save("equipment_assignments", rec)
    if unit["status"] == "AVAILABLE":
        unit["status"] = "ASSIGNED"
        touch(unit)
    services.recompute_equipment_ok(gang)
    return ok(pub(rec), 201)


@bp.get("/api/equipment-assignments")
def list_equipment_assignments():
    require_roles(*READ_ROLES)
    return list_response("equipment_assignments", {
        "gang_order_id": request.args.get("gang_order_id"),
        "equipment_unit_id": request.args.get("equipment_unit_id"),
        "status": request.args.get("status"),
    })


def _get_ea(eid):
    ea = get("equipment_assignments", eid)
    if ea is None:
        raise errors.not_found("Equipment assignment not found")
    return ea


@bp.get("/api/equipment-assignments/<eid>")
def get_equipment_assignment(eid):
    require_roles(*READ_ROLES)
    return ok(pub(_get_ea(eid)))


@bp.post("/api/equipment-assignments/<eid>/report-breakdown")
def report_breakdown(eid):
    require_roles("GangForeman")
    ea = _get_ea(eid)
    if ea["status"] not in ("RESERVED", "ACTIVE"):
        raise errors.invalid_state("Only a RESERVED or ACTIVE assignment can break down")
    ea["status"] = "DOWN"
    touch(ea)
    unit = get("equipment_units", ea["equipment_unit_id"])
    unit["status"] = "DOWN"
    unit["total_breakdowns"] += 1
    touch(unit)
    # replacement selection cascade
    replacement = services.select_replacement_unit(ea)
    if replacement is not None:
        rec = new_resource("equipment_assignments")
        rec.update({
            "gang_order_id": ea["gang_order_id"],
            "equipment_unit_id": replacement["id"],
            "window_start_utc": ea["window_start_utc"],
            "window_end_utc": ea["window_end_utc"],
            "status": "RESERVED",
            "replaced_by_assignment_id": None,
            "_ws": ea["_ws"],
            "_we": ea["_we"],
        })
        save("equipment_assignments", rec)
        ea["replaced_by_assignment_id"] = rec["id"]
        replacement["status"] = "ASSIGNED"
        touch(replacement)
    gang = get("gang_orders", ea["gang_order_id"])
    if gang is not None:
        services.recompute_equipment_ok(gang)
    return ok(pub(ea))


@bp.post("/api/equipment-assignments/<eid>/release")
def release(eid):
    require_roles("StevedoreSuperintendent")
    ea = _get_ea(eid)
    if ea["status"] not in ("RESERVED", "ACTIVE"):
        raise errors.invalid_state("Only a RESERVED or ACTIVE assignment can be released")
    services.release_equipment_assignment(ea)
    gang = get("gang_orders", ea["gang_order_id"])
    if gang is not None:
        services.recompute_equipment_ok(gang)
    return ok(pub(ea))
