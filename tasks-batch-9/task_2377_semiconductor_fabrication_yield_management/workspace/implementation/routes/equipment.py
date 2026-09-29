"""Equipment, chambers, preventive maintenance, contamination and operators."""
from flask import Blueprint, g

import calc
import clock
from auth import ALL_ROLES, require
from db import db, need, new_row, ordered, touch
from errors import fail
from response import ok
from routes.common import matches, paged
from services import cascades
from util import days_later, hours_later, r2
from validate import (TOOL_TYPES, body, q_enum, q_str, v_enum, v_num, v_str,
                      v_tool_type_list)

bp = Blueprint("equipment", __name__)

EQUIPMENT_STATES = ("IDLE", "PRODUCTIVE", "PM", "DOWN")
QUAL_STATES = ("UNQUALIFIED", "QUALIFIED", "QUAL_EXPIRED", "DISQUALIFIED")
CERT_STATUSES = ("ACTIVE", "SUSPENDED", "REVOKED")
GOWN_STATES = ("STREET", "GOWNED")


# ----------------------------------------------------------------- equipment

@bp.post("/fab/equipment")
@require("EquipmentEngineer")
def create_equipment():
    data = body()
    equipment_code = v_str(data, "equipment_code", min_len=1, max_len=32)
    tool_type = v_enum(data, "tool_type", TOOL_TYPES)
    pm_interval_hours = v_num(data, "pm_interval_hours", required=False, gt=0, default=168.0)
    purge_buffer_hours = v_num(data, "purge_buffer_hours", required=False, ge=0, default=2.0)
    hours_since_pm = v_num(data, "hours_since_pm", required=False, ge=0, default=0.0)
    if any(e["equipment_code"] == equipment_code for e in db.equipment.values()):
        fail("ERR_DUPLICATE_CODE", "equipment_code '%s' already exists" % equipment_code)
    row = new_row({
        "equipment_code": equipment_code,
        "tool_type": tool_type,
        "pm_interval_hours": pm_interval_hours,
        "purge_buffer_hours": purge_buffer_hours,
        "hours_since_pm": r2(hours_since_pm),
        "state": "IDLE",
        "available_capacity_hours": calc.INITIAL_CAPACITY_HOURS,
        "pm_started_at": None,
        "purge_until": None,
    })
    db.equipment[row["id"]] = row
    return ok(row, 201)


@bp.get("/fab/equipment")
@require(*ALL_ROLES)
def list_equipment():
    filters = {
        "tool_type": q_enum("tool_type", TOOL_TYPES),
        "state": q_enum("state", EQUIPMENT_STATES),
    }
    return paged([e for e in db.equipment.values() if matches(e, filters)])


@bp.get("/fab/equipment/<equipment_id>")
@require(*ALL_ROLES)
def read_equipment(equipment_id):
    return ok(need(db.equipment, equipment_id, "ERR_EQUIPMENT_NOT_FOUND"))


@bp.post("/fab/equipment/<equipment_id>/pm-start")
@require("EquipmentEngineer")
def pm_start(equipment_id):
    data = body()
    v_str(data, "pm_reason")
    equipment = need(db.equipment, equipment_id, "ERR_EQUIPMENT_NOT_FOUND")
    if equipment["state"] not in ("IDLE", "DOWN"):
        fail("ERR_EQUIPMENT_INVALID_STATE",
             "Equipment is %s; PM may only start from IDLE or DOWN" % equipment["state"])
    equipment["state"] = "PM"
    equipment["pm_started_at"] = clock.now()
    touch(equipment)
    return ok(equipment)


@bp.post("/fab/equipment/<equipment_id>/pm-complete")
@require("EquipmentEngineer")
def pm_complete(equipment_id):
    body()
    equipment = need(db.equipment, equipment_id, "ERR_EQUIPMENT_NOT_FOUND")
    if equipment["state"] != "PM":
        fail("ERR_EQUIPMENT_NOT_IN_PM", "Equipment is %s, not PM" % equipment["state"])

    now = clock.now()
    equipment["state"] = "IDLE"
    equipment["hours_since_pm"] = 0.0
    equipment["available_capacity_hours"] = calc.INITIAL_CAPACITY_HOURS
    equipment["purge_until"] = hours_later(now, equipment["purge_buffer_hours"])
    touch(equipment)

    chamber_ids = set()
    for chamber in cascades.chambers_of(equipment_id):
        chamber_ids.add(chamber["id"])
        if chamber["qual_state"] == "DISQUALIFIED":
            chamber["qual_state"] = "UNQUALIFIED"
            touch(chamber)

    for lot in ordered(db.lots.values()):
        if lot["hold_state"] != "QUAL_HOLD" or not lot["hold_excursion_id"]:
            continue
        excursion = db.excursions.get(lot["hold_excursion_id"])
        if excursion is not None and excursion["chamber_id"] in chamber_ids:
            cascades.release_hold(lot)
    return ok(equipment)


# ------------------------------------------------------------------ chambers

@bp.post("/fab/chambers")
@require("EquipmentEngineer")
def create_chamber():
    data = body()
    equipment_id = v_str(data, "equipment_id")
    chamber_code = v_str(data, "chamber_code", min_len=1, max_len=16)
    qualified_recipe_id = v_str(data, "qualified_recipe_id")
    particle_limit = v_num(data, "particle_limit", required=False, gt=0, default=50.0)

    need(db.equipment, equipment_id, "ERR_EQUIPMENT_NOT_FOUND")
    need(db.recipes, qualified_recipe_id, "ERR_RECIPE_NOT_FOUND")
    if any(c["equipment_id"] == equipment_id and c["chamber_code"] == chamber_code
           for c in db.chambers.values()):
        fail("ERR_DUPLICATE_CODE",
             "chamber_code '%s' already exists on this equipment" % chamber_code)

    row = new_row({
        "equipment_id": equipment_id,
        "qualified_recipe_id": qualified_recipe_id,
        "chamber_code": chamber_code,
        "particle_limit": particle_limit,
        "particle_count": 0.0,
        "qual_state": "UNQUALIFIED",
        "occupancy_state": "FREE",
        "qualified_at": None,
        "qual_expires_at": None,
    })
    db.chambers[row["id"]] = row
    return ok(row, 201)


@bp.get("/fab/chambers")
@require(*ALL_ROLES)
def list_chambers():
    filters = {
        "equipment_id": q_str("equipment_id"),
        "qualified_recipe_id": q_str("qualified_recipe_id"),
        "qual_state": q_enum("qual_state", QUAL_STATES),
    }
    return paged([c for c in db.chambers.values() if matches(c, filters)])


@bp.get("/fab/chambers/<chamber_id>")
@require(*ALL_ROLES)
def read_chamber(chamber_id):
    return ok(need(db.chambers, chamber_id, "ERR_CHAMBER_NOT_FOUND"))


@bp.post("/fab/chambers/<chamber_id>/qualification-runs")
@require("EquipmentEngineer")
def qualification_run(chamber_id):
    data = body()
    qual_result = v_enum(data, "qual_result", ("PASS", "FAIL"))
    chamber = need(db.chambers, chamber_id, "ERR_CHAMBER_NOT_FOUND")
    equipment = db.equipment[chamber["equipment_id"]]
    recipe = db.recipes[chamber["qualified_recipe_id"]]

    if equipment["state"] in ("DOWN", "PM"):
        fail("ERR_EQUIPMENT_DOWN",
             "Equipment is %s; qualification runs require an available tool" % equipment["state"])
    if recipe["status"] != "QUALIFIED":
        fail("ERR_RECIPE_RESTRICTED",
             "Recipe is %s (%s)" % (recipe["status"], recipe["restricted_reason"]))
    if chamber["qual_state"] not in ("UNQUALIFIED", "QUAL_EXPIRED"):
        fail("ERR_CHAMBER_INVALID_QUAL_STATE",
             "Chamber qual_state is %s" % chamber["qual_state"])

    if qual_result == "PASS" and chamber["particle_count"] <= chamber["particle_limit"]:
        now = clock.now()
        chamber["qual_state"] = "QUALIFIED"
        chamber["qualified_at"] = now
        chamber["qual_expires_at"] = days_later(now, recipe["qual_expiry_days"])
    touch(chamber)
    return ok(chamber)


@bp.post("/fab/chambers/<chamber_id>/particle-readings")
@require("EquipmentEngineer", "QualityManager")
def particle_reading(chamber_id):
    data = body()
    reading = v_num(data, "particle_reading")
    chamber = need(db.chambers, chamber_id, "ERR_CHAMBER_NOT_FOUND")

    reading = r2(reading)
    chamber["particle_count"] = reading
    touch(chamber)
    if reading > chamber["particle_limit"]:
        cascades.particle_escalation(chamber, reading)
    return ok(chamber)


# ----------------------------------------------------------------- operators

@bp.post("/fab/operators")
@require("QualityManager")
def create_operator():
    data = body()
    badge_id = v_str(data, "badge_id", min_len=1, max_len=16)
    full_name = v_str(data, "full_name")
    certified_tool_types = v_tool_type_list(data, "certified_tool_types")
    if any(o["badge_id"] == badge_id for o in db.operators.values()):
        fail("ERR_DUPLICATE_CODE", "badge_id '%s' already exists" % badge_id)
    row = new_row({
        "badge_id": badge_id,
        "full_name": full_name,
        "certified_tool_types": certified_tool_types,
        "gown_state": "STREET",
        "gowned_at": None,
        "cert_status": "ACTIVE",
    })
    db.operators[row["id"]] = row
    return ok(row, 201)


@bp.get("/fab/operators")
@require(*ALL_ROLES)
def list_operators():
    filters = {
        "cert_status": q_enum("cert_status", CERT_STATUSES),
        "gown_state": q_enum("gown_state", GOWN_STATES),
    }
    return paged([o for o in db.operators.values() if matches(o, filters)])


@bp.get("/fab/operators/<operator_id>")
@require(*ALL_ROLES)
def read_operator(operator_id):
    return ok(need(db.operators, operator_id, "ERR_OPERATOR_NOT_FOUND"))


@bp.patch("/fab/operators/<operator_id>")
@require("Operator", "QualityManager")
def patch_operator(operator_id):
    data = body()
    # Field-level authorisation: gowning belongs to the operator, certification to QA.
    if g.role == "Operator" and "cert_status" in data:
        fail("ERR_UNAUTHORIZED", "An Operator may not change cert_status")
    if g.role == "QualityManager" and "gown_state" in data:
        fail("ERR_UNAUTHORIZED", "A QualityManager may not change gown_state")

    gown_state = v_enum(data, "gown_state", GOWN_STATES, required=False)
    cert_status = v_enum(data, "cert_status", CERT_STATUSES, required=False)
    if gown_state is None and cert_status is None:
        fail("ERR_VALIDATION", "Supply gown_state or cert_status")

    operator = need(db.operators, operator_id, "ERR_OPERATOR_NOT_FOUND")
    if g.role == "Operator" and g.user_id != operator["id"]:
        fail("ERR_OPERATOR_IDENTITY_MISMATCH",
             "X-User-ID does not match the operator being patched")

    if gown_state is not None:
        if operator["cert_status"] != "ACTIVE":
            fail("ERR_OPERATOR_CERT_INACTIVE",
                 "Operator certification is %s" % operator["cert_status"])
        if gown_state != operator["gown_state"]:
            operator["gown_state"] = gown_state
            operator["gowned_at"] = clock.now() if gown_state == "GOWNED" else None
    else:
        if operator["cert_status"] == "REVOKED" and cert_status != "REVOKED":
            fail("ERR_VALIDATION", "REVOKED is a terminal certification state")
        operator["cert_status"] = cert_status
        if cert_status == "REVOKED":
            operator["gown_state"] = "STREET"
            operator["gowned_at"] = None
    touch(operator)
    return ok(operator)
