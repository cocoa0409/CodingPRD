"""Mixed-model sequencing, release to the floor and the quality gate chain."""

import calc
import lookup
import response
import serializers as ser
import services
import validation as v
from db import db, new_record, touch
from errors import ApiError
from flask import Blueprint
from middleware import (ENGINEERING_LEAD, LINE_OPERATOR, PLANT_ADMIN, PRODUCTION_PLANNER,
                        QUALITY_INSPECTOR, WARRANTY_ANALYST, endpoint)

production_bp = Blueprint("production", __name__)

SLOT_STATUSES = ("PLANNED", "SEQUENCED", "RELEASED", "BUILT", "CANCELLED")
ASSEMBLY_STATUSES = ("IN_STATION", "ASSEMBLED", "REWORK", "SHIPPED")
QUALITY_STATUSES = ("PENDING", "SAFETY_PASSED", "GATED", "CERTIFIED", "QUARANTINED")
TIERS = ("A_PLUS", "A", "B")
TEST_TYPES = ("ELECTRICAL_SAFETY", "LEAK", "FUNCTIONAL_CYCLE", "ENERGY", "WATER")
TEST_STATUSES = ("RECORDED", "VOIDED")
TEST_RESULTS = ("PASS", "FAIL", "MEASURED")

LIMIT_FIELD = {
    "ELECTRICAL_SAFETY": "hipot_leakage_ma_limit",
    "LEAK": "leak_limit_ml_per_min",
    "FUNCTIONAL_CYCLE": "functional_cycle_count_required",
    "ENERGY": "energy_kwh_limit",
    "WATER": "water_liters_limit",
}
GATE_REQUIREMENTS = {
    "LEAK": ("SAFETY_PASSED", "GATED"),
    "FUNCTIONAL_CYCLE": ("SAFETY_PASSED", "GATED"),
    "ENERGY": ("GATED",),
    "WATER": ("GATED",),
}


# =========================================================================== #
# BuildSlot
# =========================================================================== #
@production_bp.post("/build-slots")
@endpoint([PRODUCTION_PLANNER, PLANT_ADMIN])
def create_build_slot():
    body = v.body()
    line_id = v.req_str(body, "line_id")
    model_variant_id = v.req_str(body, "model_variant_id")
    sequence_index = v.req_int(body, "sequence_index", minimum=1)
    planned_start = v.req_dt(body, "planned_start")

    lookup.must(lookup.LINE, line_id)
    lookup.must(lookup.MODEL_VARIANT, model_variant_id)

    for other in calc.line_slots(line_id):
        if other["sequence_index"] == sequence_index and other["status"] in calc.LIVE_SLOT_STATUSES:
            raise ApiError("ERR_SEQUENCE_INDEX_TAKEN")

    slot = new_record()
    slot.update({
        "line_id": line_id,
        "model_variant_id": model_variant_id,
        "shift_plan_id": None,
        "sync_delivery_call_id": None,
        "sequence_index": sequence_index,
        "planned_start": planned_start,
        "option_points_snapshot": None,
        "labor_minutes_snapshot": None,
        "presentation_allocations": [],
        "allocated_slot_units": 0,
        "status": "PLANNED",
    })
    db.build_slots[slot["id"]] = slot
    return response.created(ser.build_slot_out(slot))


@production_bp.get("/build-slots/<slot_id>")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, LINE_OPERATOR, QUALITY_INSPECTOR, ENGINEERING_LEAD])
def read_build_slot(slot_id):
    slot = lookup.must(lookup.BUILD_SLOT, slot_id)
    return response.ok(ser.build_slot_out(slot))


@production_bp.get("/build-slots")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, LINE_OPERATOR, QUALITY_INSPECTOR, ENGINEERING_LEAD])
def list_build_slots():
    limit, offset = v.pagination()
    line_id = v.q_str("line_id")
    model_variant_id = v.q_str("model_variant_id")
    shift_plan_id = v.q_str("shift_plan_id")
    sync_call_id = v.q_str("sync_delivery_call_id")
    status = v.q_enum("status", SLOT_STATUSES)

    lookup.must_fk(lookup.LINE, line_id)
    lookup.must_fk(lookup.MODEL_VARIANT, model_variant_id)
    lookup.must_fk(lookup.SHIFT_PLAN, shift_plan_id)
    lookup.must_fk(lookup.DELIVERY_CALL, sync_call_id)

    items = list(db.build_slots.values())
    if line_id is not None:
        items = [s for s in items if s["line_id"] == line_id]
    if model_variant_id is not None:
        items = [s for s in items if s["model_variant_id"] == model_variant_id]
    if shift_plan_id is not None:
        items = [s for s in items if s["shift_plan_id"] == shift_plan_id]
    if sync_call_id is not None:
        items = [s for s in items if s["sync_delivery_call_id"] == sync_call_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]

    items.sort(key=lambda s: (s["sequence_index"], s["created_at"], s["_seq"]))
    window, total = v.page(items, limit, offset)
    return response.ok_list([ser.build_slot_out(s) for s in window], limit, offset, total)


@production_bp.post("/build-slots/<slot_id>/sequence")
@endpoint([PRODUCTION_PLANNER])
def sequence_build_slot(slot_id):
    slot = lookup.must(lookup.BUILD_SLOT, slot_id)
    services.sequence_slot(slot)
    return response.ok(ser.build_slot_out(slot))


@production_bp.post("/build-slots/<slot_id>/de-sequence")
@endpoint([PRODUCTION_PLANNER])
def de_sequence_build_slot(slot_id):
    slot = lookup.must(lookup.BUILD_SLOT, slot_id)
    if slot["status"] != "SEQUENCED":
        raise ApiError("ERR_INVALID_STATE")
    services.desequence_slot(slot)
    return response.ok(ser.build_slot_out(slot))


@production_bp.post("/build-slots/<slot_id>/release")
@endpoint([LINE_OPERATOR])
def release_build_slot(slot_id):
    slot = lookup.must(lookup.BUILD_SLOT, slot_id)
    line = db.lines.get(slot["line_id"])
    variant = db.model_variants.get(slot["model_variant_id"])

    # 9 — state
    if slot["status"] != "SEQUENCED":
        raise ApiError("ERR_INVALID_STATE")
    # 14 — governing variant released
    if variant is None or variant["status"] != "RELEASED":
        raise ApiError("ERR_MODEL_NOT_RELEASED")
    # 21 — tooling family match
    if line is None or variant["family_code"] != line["current_family_code"]:
        raise ApiError("ERR_CHANGEOVER_REQUIRED")
    # 26 — posture must be fully OPEN
    if calc.line_posture(line) != "OPEN":
        raise ApiError("ERR_LINE_POSTURE_BLOCKED")

    slot["status"] = "RELEASED"
    touch(slot)

    unit = new_record()
    unit.update({
        "build_slot_id": slot["id"],
        "serial_number": "%s-%06d" % (line["line_code"], slot["sequence_index"]),
        "built_at_sequence_index": slot["sequence_index"],
        "assembly_status": "IN_STATION",
        "quality_status": "PENDING",
        "rework_count": 0,
        "efficiency_index": None,
        "certification_tier": None,
    })
    db.production_units[unit["id"]] = unit
    services.touch_line(line)
    return response.created(ser.production_unit_out(unit))


# =========================================================================== #
# ProductionUnit
# =========================================================================== #
@production_bp.get("/production-units/<unit_id>")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, LINE_OPERATOR, QUALITY_INSPECTOR, ENGINEERING_LEAD,
           WARRANTY_ANALYST])
def read_production_unit(unit_id):
    unit = lookup.must(lookup.PRODUCTION_UNIT, unit_id)
    return response.ok(ser.production_unit_out(unit))


@production_bp.get("/production-units")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, LINE_OPERATOR, QUALITY_INSPECTOR, ENGINEERING_LEAD,
           WARRANTY_ANALYST])
def list_production_units():
    limit, offset = v.pagination()
    build_slot_id = v.q_str("build_slot_id")
    assembly_status = v.q_enum("assembly_status", ASSEMBLY_STATUSES)
    quality_status = v.q_enum("quality_status", QUALITY_STATUSES)
    tier = v.q_enum("certification_tier", TIERS)

    lookup.must_fk(lookup.BUILD_SLOT, build_slot_id)

    items = list(db.production_units.values())
    if build_slot_id is not None:
        items = [u for u in items if u["build_slot_id"] == build_slot_id]
    if assembly_status is not None:
        items = [u for u in items if u["assembly_status"] == assembly_status]
    if quality_status is not None:
        items = [u for u in items if u["quality_status"] == quality_status]
    if tier is not None:
        items = [u for u in items if u["certification_tier"] == tier]

    items.sort(key=lambda u: (u["built_at_sequence_index"], u["created_at"], u["_seq"]))
    window, total = v.page(items, limit, offset)
    return response.ok_list([ser.production_unit_out(u) for u in window], limit, offset, total)


def _governing_variant(unit):
    slot = db.build_slots.get(unit["build_slot_id"])
    return db.model_variants.get(slot["model_variant_id"]) if slot else None


# =========================================================================== #
# QualityTest
# =========================================================================== #
@production_bp.post("/production-units/<unit_id>/quality-tests")
@endpoint([QUALITY_INSPECTOR])
def create_quality_test(unit_id):
    body = v.body()
    test_type = v.req_enum(body, "test_type", TEST_TYPES)
    measured_value = v.req_num(body, "measured_value", minimum=0)
    unit = lookup.must(lookup.PRODUCTION_UNIT, unit_id)
    variant = _governing_variant(unit)
    if variant is None:
        raise ApiError("ERR_MODEL_VARIANT_NOT_FOUND")

    # 10 — applicability
    if test_type == "LEAK" and not variant["requires_leak_test"]:
        raise ApiError("ERR_TEST_NOT_APPLICABLE")
    if test_type == "WATER" and variant["water_liters_limit"] is None:
        raise ApiError("ERR_TEST_NOT_APPLICABLE")
    limit_value = variant[LIMIT_FIELD[test_type]]
    if limit_value is None:
        raise ApiError("ERR_TEST_NOT_APPLICABLE")
    # 11 — gate order
    required = GATE_REQUIREMENTS.get(test_type)
    if required is not None and unit["quality_status"] not in required:
        raise ApiError("ERR_QUALITY_GATE_ORDER")
    # 12 — quarantined units accept no new measurement
    if unit["quality_status"] == "QUARANTINED":
        raise ApiError("ERR_UNIT_QUARANTINED")

    if test_type in ("ENERGY", "WATER"):
        result = "MEASURED"
    elif test_type == "FUNCTIONAL_CYCLE":
        result = "PASS" if calc.d(measured_value) >= calc.d(limit_value) else "FAIL"
    else:
        result = "PASS" if calc.d(measured_value) <= calc.d(limit_value) else "FAIL"

    test = new_record(versioned=False)
    test.update({
        "production_unit_id": unit["id"],
        "test_type": test_type,
        "measured_value": measured_value,
        "limit_value": limit_value,
        "result": result,
        "status": "RECORDED",
    })
    db.quality_tests[test["id"]] = test

    before = (unit["assembly_status"], unit["quality_status"], unit["rework_count"])
    services.advance_quality(unit, variant, test)
    if (unit["assembly_status"], unit["quality_status"], unit["rework_count"]) != before:
        touch(unit)
    return response.created(ser.quality_test_out(test))


@production_bp.get("/production-units/<unit_id>/quality-tests")
@endpoint([PLANT_ADMIN, QUALITY_INSPECTOR, ENGINEERING_LEAD, WARRANTY_ANALYST])
def list_quality_tests(unit_id):
    limit, offset = v.pagination()
    test_type = v.q_enum("test_type", TEST_TYPES)
    status = v.q_enum("status", TEST_STATUSES)
    result = v.q_enum("result", TEST_RESULTS)
    lookup.must(lookup.PRODUCTION_UNIT, unit_id)

    items = [t for t in db.quality_tests.values() if t["production_unit_id"] == unit_id]
    if test_type is not None:
        items = [t for t in items if t["test_type"] == test_type]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if result is not None:
        items = [t for t in items if t["result"] == result]
    items = lookup.sort_created(items)
    window, total = v.page(items, limit, offset)
    return response.ok_list([ser.quality_test_out(t) for t in window], limit, offset, total)


# =========================================================================== #
# unit actions
# =========================================================================== #
@production_bp.post("/production-units/<unit_id>/clear-quarantine")
@endpoint([QUALITY_INSPECTOR])
def clear_quarantine(unit_id):
    body = v.body()
    v.opt_str(body, "note")
    unit = lookup.must(lookup.PRODUCTION_UNIT, unit_id)
    if unit["quality_status"] != "QUARANTINED" or unit["assembly_status"] != "REWORK":
        raise ApiError("ERR_INVALID_STATE")

    voided = [t for t in db.quality_tests.values()
              if t["production_unit_id"] == unit["id"]
              and t["result"] == "FAIL"
              and t["status"] == "RECORDED"]
    for test in voided:
        test["status"] = "VOIDED"

    unit["quality_status"] = "PENDING"
    unit["assembly_status"] = "IN_STATION"
    touch(unit)
    return response.ok(ser.production_unit_out(unit))


@production_bp.post("/production-units/<unit_id>/certify")
@endpoint([QUALITY_INSPECTOR])
def certify_unit(unit_id):
    unit = lookup.must(lookup.PRODUCTION_UNIT, unit_id)
    variant = _governing_variant(unit)

    # 9 — state, including the ENERGY / WATER measurement requirement
    if unit["quality_status"] != "GATED":
        raise ApiError("ERR_INVALID_STATE")
    if not calc._recorded_tests(unit["id"], "ENERGY") or not calc._recorded_tests(unit["id"], "WATER"):
        raise ApiError("ERR_INVALID_STATE")
    index = calc.efficiency_index(unit["id"], "CERTIFICATION_AVERAGE")
    if index is None:
        raise ApiError("ERR_INVALID_STATE")
    # 13 — efficiency ceiling
    if index > calc.TIER_B_MAX:
        raise ApiError("ERR_EFFICIENCY_LIMIT_EXCEEDED")
    # 14 — governing variant released
    if variant is None or variant["status"] != "RELEASED":
        raise ApiError("ERR_MODEL_NOT_RELEASED")

    unit["efficiency_index"] = index
    unit["certification_tier"] = calc.certification_tier(index)
    unit["quality_status"] = "CERTIFIED"
    touch(unit)
    return response.ok(ser.production_unit_out(unit))


@production_bp.post("/production-units/<unit_id>/complete-assembly")
@endpoint([LINE_OPERATOR])
def complete_assembly(unit_id):
    unit = lookup.must(lookup.PRODUCTION_UNIT, unit_id)
    # 12 — a quarantined unit accepts no assembly progress
    if unit["quality_status"] == "QUARANTINED":
        raise ApiError("ERR_UNIT_QUARANTINED")
    # 9 — state
    if unit["assembly_status"] != "IN_STATION":
        raise ApiError("ERR_INVALID_STATE")

    unit["assembly_status"] = "ASSEMBLED"
    touch(unit)
    slot = db.build_slots.get(unit["build_slot_id"])
    if slot is not None and slot["status"] == "RELEASED":
        slot["status"] = "BUILT"          # bubble-up
        touch(slot)
    return response.ok(ser.production_unit_out(unit))


@production_bp.post("/production-units/<unit_id>/ship")
@endpoint([LINE_OPERATOR])
def ship_unit(unit_id):
    unit = lookup.must(lookup.PRODUCTION_UNIT, unit_id)
    # 12 — a quarantined unit accepts no assembly progress
    if unit["quality_status"] == "QUARANTINED":
        raise ApiError("ERR_UNIT_QUARANTINED")
    # 9 — state, including the cross-dimension certification guard
    if unit["assembly_status"] != "ASSEMBLED":
        raise ApiError("ERR_INVALID_STATE")
    if unit["quality_status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_STATE")

    unit["assembly_status"] = "SHIPPED"
    touch(unit)
    slot = db.build_slots.get(unit["build_slot_id"])
    if slot is not None:
        services.release_allocations(slot)
    return response.ok(ser.production_unit_out(unit))
