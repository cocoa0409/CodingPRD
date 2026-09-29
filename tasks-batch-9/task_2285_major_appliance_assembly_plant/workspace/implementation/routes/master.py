"""Master data: logical clock, lines, stations, model variants, suppliers,
parts and bill-of-materials lines."""

import calc
import lookup
import response
import serializers as ser
import services
import validation as v
from db import db, iso, new_record, touch
from errors import ApiError, invalid
from flask import Blueprint, g
from middleware import (ENGINEERING_LEAD, INTERNAL_ROLES, LINE_OPERATOR, PLANT_ADMIN,
                        PRODUCTION_PLANNER, QUALITY_INSPECTOR, SUPPLIER_PORTAL,
                        WARRANTY_ANALYST, endpoint)

master_bp = Blueprint("master", __name__)

LIFECYCLE_STATUSES = ("ACTIVE", "CHANGE_PENDING", "SERVICE_ONLY", "OBSOLETE")
BOM_STATUSES = ("ACTIVE", "SUPERSEDED")


# =========================================================================== #
# logical clock
# =========================================================================== #
@master_bp.post("/_clock/set_current_utc")
@endpoint(INTERNAL_ROLES)
def set_clock():
    body = v.body()
    current = v.req_dt(body, "current_utc")
    db.clock = current
    return response.ok({"current_utc": iso(current)})


# =========================================================================== #
# Line
# =========================================================================== #
@master_bp.post("/lines")
@endpoint([PLANT_ADMIN])
def create_line():
    body = v.body()
    line_code = v.req_str(body, "line_code", min_len=1, max_len=16)
    takt_seconds = v.req_int(body, "takt_seconds", minimum=1)
    limit_pct = v.req_num(body, "option_load_limit_pct", exclusive_min=0, maximum=100)
    baseline = v.req_int(body, "baseline_headcount", minimum=1)
    family = v.req_str(body, "current_family_code")

    for existing in db.lines.values():
        if existing["line_code"] == line_code:
            raise ApiError("ERR_DUPLICATE_CODE")

    line = new_record()
    line.update({
        "line_code": line_code,
        "takt_seconds": takt_seconds,
        "option_load_limit_pct": limit_pct,
        "baseline_headcount": baseline,
        "current_family_code": family,
        "operating_mode": "RUNNING",
        "stop_reason": None,
        "changeover_count": 0,
        "checkpoint_index": 0,
    })
    db.lines[line["id"]] = line
    return response.created(ser.line_out(line))


@master_bp.get("/lines/<line_id>")
@endpoint(INTERNAL_ROLES)
def read_line(line_id):
    line = lookup.must(lookup.LINE, line_id)
    return response.ok(ser.line_out(line))


@master_bp.post("/lines/<line_id>/stop")
@endpoint([LINE_OPERATOR, PLANT_ADMIN])
def stop_line(line_id):
    body = v.body()
    reason = v.req_str(body, "reason")
    line = lookup.must(lookup.LINE, line_id)
    if line["operating_mode"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE")
    line["operating_mode"] = "STOPPED"
    line["stop_reason"] = reason
    touch(line)
    return response.ok(ser.line_out(line))


@master_bp.post("/lines/<line_id>/start")
@endpoint([LINE_OPERATOR, PLANT_ADMIN])
def start_line(line_id):
    body = v.body()
    to_family = v.opt_str(body, "to_family_code", min_len=1)
    line = lookup.must(lookup.LINE, line_id)
    if line["operating_mode"] != "STOPPED":
        raise ApiError("ERR_INVALID_STATE")

    changeover = to_family is not None and to_family != line["current_family_code"]
    plan = None
    if changeover:
        plans = services.covering_plans(line["id"], db.clock)
        if len(plans) != 1:
            raise ApiError("ERR_NO_SHIFT_COVERAGE")
        plan = plans[0]

    line["operating_mode"] = "RUNNING"
    line["stop_reason"] = None
    if changeover:
        line["current_family_code"] = to_family
        line["changeover_count"] += 1
        plan["_booked_changeover_minutes"] = (
            plan.get("_booked_changeover_minutes", 0) + int(calc.CHANGEOVER_MINUTES))
        services.recompute_plan(plan)
    touch(line)
    return response.ok(ser.line_out(line))


@master_bp.post("/lines/<line_id>/run-checkpoint")
@endpoint([PRODUCTION_PLANNER, PLANT_ADMIN])
def run_checkpoint(line_id):
    line = lookup.must(lookup.LINE, line_id)
    return response.ok(services.run_checkpoint(line))


# =========================================================================== #
# Station
# =========================================================================== #
@master_bp.post("/stations")
@endpoint([PLANT_ADMIN])
def create_station():
    body = v.body()
    line_id = v.req_str(body, "line_id")
    station_code = v.req_str(body, "station_code")
    position_index = v.req_int(body, "position_index", minimum=1)
    capacity = v.req_int(body, "presentation_slot_capacity", minimum=0)
    cycle_seconds = v.req_int(body, "station_cycle_seconds", minimum=1)

    line = lookup.must(lookup.LINE, line_id)

    for existing in db.stations.values():
        if existing["line_id"] != line_id:
            continue
        if existing["station_code"] == station_code or existing["position_index"] == position_index:
            raise ApiError("ERR_DUPLICATE_CODE")

    station = new_record()
    station.update({
        "line_id": line_id,
        "station_code": station_code,
        "position_index": position_index,
        "presentation_slot_capacity": capacity,
        "presentation_slots_used": 0,
        "station_cycle_seconds": cycle_seconds,
    })
    db.stations[station["id"]] = station
    touch(line)  # station creation advances the line's version (PRD §2.5)
    return response.created(ser.station_out(station))


@master_bp.get("/stations/<station_id>")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, LINE_OPERATOR, QUALITY_INSPECTOR, ENGINEERING_LEAD])
def read_station(station_id):
    station = lookup.must(lookup.STATION, station_id)
    return response.ok(ser.station_out(station))


@master_bp.get("/lines/<line_id>/stations")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, LINE_OPERATOR, QUALITY_INSPECTOR, ENGINEERING_LEAD])
def list_line_stations(line_id):
    limit, offset = v.pagination()
    lookup.must(lookup.LINE, line_id)
    items = calc.line_stations(line_id)
    window, total = v.page(items, limit, offset)
    return response.ok_list([ser.station_out(s) for s in window], limit, offset, total)


# =========================================================================== #
# ModelVariant
# =========================================================================== #
@master_bp.post("/model-variants")
@endpoint([PLANT_ADMIN])
def create_model_variant():
    body = v.body()
    model_code = v.req_str(body, "model_code")
    family_code = v.req_str(body, "family_code")
    option_codes = v.req_str_array(body, "option_codes")
    points = v.req_int(body, "option_content_points", minimum=0,
                       maximum=calc.MAX_POINTS_PER_SLOT)
    labor_minutes = v.req_num(body, "labor_minutes", exclusive_min=0)
    cycles = v.req_int(body, "functional_cycle_count_required", minimum=1)
    requires_leak = v.opt_bool(body, "requires_leak_test", default=False)
    hipot = v.opt_num(body, "hipot_leakage_ma_limit", exclusive_min=0)
    leak_limit = v.opt_num(body, "leak_limit_ml_per_min", exclusive_min=0)
    energy = v.opt_num(body, "energy_kwh_limit", exclusive_min=0)
    water = v.opt_num(body, "water_liters_limit", exclusive_min=0)
    if requires_leak and leak_limit is None:
        raise invalid("leak_limit_ml_per_min is required when requires_leak_test is true")
    if not requires_leak:
        leak_limit = None

    for existing in db.model_variants.values():
        if existing["model_code"] == model_code:
            raise ApiError("ERR_DUPLICATE_CODE")

    variant = new_record()
    variant.update({
        "model_code": model_code,
        "family_code": family_code,
        "option_codes": option_codes,
        "option_content_points": points,
        "labor_minutes": labor_minutes,
        "requires_leak_test": requires_leak,
        "hipot_leakage_ma_limit": hipot,
        "leak_limit_ml_per_min": leak_limit,
        "functional_cycle_count_required": cycles,
        "energy_kwh_limit": energy,
        "water_liters_limit": water,
        "status": "DRAFT",
    })
    db.model_variants[variant["id"]] = variant
    return response.created(ser.model_variant_out(variant))


@master_bp.get("/model-variants/<variant_id>")
@endpoint(INTERNAL_ROLES)
def read_model_variant(variant_id):
    variant = lookup.must(lookup.MODEL_VARIANT, variant_id)
    return response.ok(ser.model_variant_out(variant))


@master_bp.post("/model-variants/<variant_id>/release")
@endpoint([PLANT_ADMIN])
def release_model_variant(variant_id):
    variant = lookup.must(lookup.MODEL_VARIANT, variant_id)
    if variant["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    variant["status"] = "RELEASED"
    touch(variant)
    return response.ok(ser.model_variant_out(variant))


@master_bp.post("/model-variants/<variant_id>/obsolete")
@endpoint([PLANT_ADMIN])
def obsolete_model_variant(variant_id):
    variant = lookup.must(lookup.MODEL_VARIANT, variant_id)
    if variant["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE")
    variant["status"] = "OBSOLETE"
    touch(variant)
    return response.ok(ser.model_variant_out(variant))


# =========================================================================== #
# Supplier
# =========================================================================== #
@master_bp.post("/suppliers")
@endpoint([PLANT_ADMIN])
def create_supplier():
    body = v.body()
    supplier_code = v.req_str(body, "supplier_code")
    name = v.req_str(body, "name")
    window = v.req_int(body, "sync_window_minutes", minimum=1)

    for existing in db.suppliers.values():
        if existing["supplier_code"] == supplier_code:
            raise ApiError("ERR_DUPLICATE_CODE")

    supplier = new_record()
    supplier.update({
        "supplier_code": supplier_code,
        "name": name,
        "sync_window_minutes": window,
        "on_time_score": calc.SCORE_START,
        "status": "APPROVED",
        "delivered_on_time_count": 0,
        "delivered_late_count": 0,
        "missed_count": 0,
        "quality_penalty_count": 0,
    })
    db.suppliers[supplier["id"]] = supplier
    return response.created(ser.supplier_out(supplier))


@master_bp.get("/suppliers/<supplier_id>")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, QUALITY_INSPECTOR, ENGINEERING_LEAD,
           WARRANTY_ANALYST, SUPPLIER_PORTAL])
def read_supplier(supplier_id):
    supplier = lookup.must(lookup.SUPPLIER, supplier_id)
    if g.role == SUPPLIER_PORTAL and supplier["id"] != g.user_id:
        raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
    return response.ok(ser.supplier_out(supplier))


# =========================================================================== #
# Part
# =========================================================================== #
@master_bp.post("/parts")
@endpoint([PLANT_ADMIN])
def create_part():
    body = v.body()
    part_number = v.req_str(body, "part_number")
    supplier_id = v.req_str(body, "supplier_id")
    is_sequenced = v.opt_bool(body, "is_sequenced_module", default=False)
    max_units = v.req_int(body, "line_side_max_units", minimum=1)

    lookup.must(lookup.SUPPLIER, supplier_id)

    for existing in db.parts.values():
        if existing["part_number"] == part_number:
            raise ApiError("ERR_DUPLICATE_CODE")

    part = new_record()
    part.update({
        "part_number": part_number,
        "supplier_id": supplier_id,
        "is_sequenced_module": is_sequenced,
        "line_side_max_units": max_units,
        "lifecycle_status": "ACTIVE",
        "service_obligation_until": None,
        "field_failure_count": 0,
        "cohort_failure_rate_per_1000": calc.d("0.00"),
    })
    db.parts[part["id"]] = part
    return response.created(ser.part_out(part))


@master_bp.get("/parts/<part_id>")
@endpoint(INTERNAL_ROLES)
def read_part(part_id):
    part = lookup.must(lookup.PART, part_id)
    return response.ok(ser.part_out(part))


@master_bp.get("/parts")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, ENGINEERING_LEAD, WARRANTY_ANALYST,
           SUPPLIER_PORTAL])
def list_parts():
    limit, offset = v.pagination()
    supplier_id = v.q_str("supplier_id")
    lifecycle = v.q_enum("lifecycle_status", LIFECYCLE_STATUSES)
    sequenced = v.q_bool("is_sequenced_module")

    lookup.must_fk(lookup.SUPPLIER, supplier_id)
    if g.role == SUPPLIER_PORTAL:
        if supplier_id is not None and supplier_id != g.user_id:
            raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
        supplier_id = g.user_id

    items = list(db.parts.values())
    if supplier_id is not None:
        items = [p for p in items if p["supplier_id"] == supplier_id]
    if lifecycle is not None:
        items = [p for p in items if p["lifecycle_status"] == lifecycle]
    if sequenced is not None:
        items = [p for p in items if p["is_sequenced_module"] == sequenced]
    items = lookup.sort_created(items)
    window, total = v.page(items, limit, offset)
    return response.ok_list([ser.part_out(p) for p in window], limit, offset, total)


@master_bp.post("/parts/<part_id>/obsolete")
@endpoint([PLANT_ADMIN])
def obsolete_part(part_id):
    part = lookup.must(lookup.PART, part_id)
    if part["lifecycle_status"] != "SERVICE_ONLY":
        raise ApiError("ERR_INVALID_STATE")
    deadline = part["service_obligation_until"]
    if deadline is not None and db.clock <= deadline:
        raise ApiError("ERR_SERVICE_OBLIGATION_ACTIVE")
    part["lifecycle_status"] = "OBSOLETE"
    touch(part)
    return response.ok(ser.part_out(part))


@master_bp.get("/parts/<part_id>/warranty-metrics")
@endpoint([PLANT_ADMIN, ENGINEERING_LEAD, WARRANTY_ANALYST])
def part_warranty_metrics(part_id):
    part = lookup.must(lookup.PART, part_id)
    metrics = calc.warranty_metrics(part["id"])
    cohort_rate = metrics["cohort_failure_rate_per_1000"]
    return response.ok({
        "part_id": part["id"],
        "failure_count": metrics["failure_count"],
        "cohort_units": metrics["cohort_units"],
        "total_field_hours": calc.num(metrics["total_field_hours"]),
        "cohort_failure_rate_per_1000": calc.num(cohort_rate),
        "shipped_exposure_rate_per_1000": calc.num(metrics["shipped_exposure_rate_per_1000"]),
        "trigger_threshold": calc.num(calc.WARRANTY_RATE_TRIGGER),
        "trigger_breached": bool(cohort_rate >= calc.WARRANTY_RATE_TRIGGER),
    })


# =========================================================================== #
# BomLine
# =========================================================================== #
@master_bp.post("/bom-lines")
@endpoint([PLANT_ADMIN, ENGINEERING_LEAD])
def create_bom_line():
    body = v.body()
    model_variant_id = v.req_str(body, "model_variant_id")
    part_id = v.req_str(body, "part_id")
    station_id = v.req_str(body, "station_id")
    position_code = v.req_str(body, "bom_position_code")
    qty = v.req_num(body, "qty_per_unit", minimum=1)
    effective_from = v.opt_int(body, "effective_from_sequence", default=1, minimum=1)
    expected_version = v.req_int(body, "expected_model_variant_version")

    variant = lookup.must(lookup.MODEL_VARIANT, model_variant_id)
    part = lookup.must(lookup.PART, part_id)
    lookup.must(lookup.STATION, station_id)

    if expected_version != variant["version"]:
        raise ApiError("ERR_STALE_MODEL_VARIANT_VERSION")
    if variant["status"] == "OBSOLETE":
        raise ApiError("ERR_MODEL_NOT_RELEASED")
    if part["lifecycle_status"] == "OBSOLETE":
        raise ApiError("ERR_PART_CHANGE_PENDING")

    bom_line = new_record()
    bom_line.update({
        "model_variant_id": model_variant_id,
        "part_id": part_id,
        "station_id": station_id,
        "bom_position_code": position_code,
        "qty_per_unit": qty,
        "effective_from_sequence": effective_from,
        "superseded_by_bom_line_id": None,
        "created_by_change_id": None,
        "status": "ACTIVE",
    })
    db.bom_lines[bom_line["id"]] = bom_line

    superseded = [b for b in db.bom_lines.values()
                  if b["id"] != bom_line["id"]
                  and b["model_variant_id"] == model_variant_id
                  and b["bom_position_code"] == position_code
                  and b["status"] == "ACTIVE"
                  and b["effective_from_sequence"] >= effective_from]
    superseded.sort(key=lambda b: (b["effective_from_sequence"], b["created_at"], b["id"]))
    for old in superseded:
        old["status"] = "SUPERSEDED"
        old["superseded_by_bom_line_id"] = bom_line["id"]
        touch(old)

    touch(variant)  # authoring a BOM line advances the variant's version
    return response.created(ser.bom_line_out(bom_line))


@master_bp.get("/bom-lines/<bom_line_id>")
@endpoint(INTERNAL_ROLES)
def read_bom_line(bom_line_id):
    bom_line = lookup.must(lookup.BOM_LINE, bom_line_id)
    return response.ok(ser.bom_line_out(bom_line))


@master_bp.get("/bom-lines")
@endpoint(INTERNAL_ROLES)
def list_bom_lines():
    limit, offset = v.pagination()
    model_variant_id = v.q_str("model_variant_id")
    part_id = v.q_str("part_id")
    station_id = v.q_str("station_id")
    superseded_by = v.q_str("superseded_by_bom_line_id")
    created_by_change = v.q_str("created_by_change_id")
    position_code = v.q_str("bom_position_code")
    status = v.q_enum("status", BOM_STATUSES)
    effective_at = v.q_int("effective_at_sequence", minimum=1)

    lookup.must_fk(lookup.MODEL_VARIANT, model_variant_id)
    lookup.must_fk(lookup.PART, part_id)
    lookup.must_fk(lookup.STATION, station_id)
    lookup.must_fk(lookup.BOM_LINE, superseded_by)
    lookup.must_fk(lookup.ENGINEERING_CHANGE, created_by_change)

    if effective_at is not None:
        include_superseded = status == "SUPERSEDED"
        variant_ids = ([model_variant_id] if model_variant_id is not None
                       else sorted({b["model_variant_id"] for b in db.bom_lines.values()}))
        items = []
        for variant_id in variant_ids:
            resolved = calc.resolve_bom(variant_id, effective_at,
                                        include_superseded=include_superseded)
            items.extend(resolved.values())
    else:
        items = list(db.bom_lines.values())
        if model_variant_id is not None:
            items = [b for b in items if b["model_variant_id"] == model_variant_id]
        if status is not None:
            items = [b for b in items if b["status"] == status]

    if part_id is not None:
        items = [b for b in items if b["part_id"] == part_id]
    if station_id is not None:
        items = [b for b in items if b["station_id"] == station_id]
    if superseded_by is not None:
        items = [b for b in items if b["superseded_by_bom_line_id"] == superseded_by]
    if created_by_change is not None:
        items = [b for b in items if b["created_by_change_id"] == created_by_change]
    if position_code is not None:
        items = [b for b in items if b["bom_position_code"] == position_code]

    items = lookup.sort_created(items)
    window, total = v.page(items, limit, offset)
    return response.ok_list([ser.bom_line_out(b) for b in window], limit, offset, total)
