"""Zones, posture overrides and varieties."""
from flask import Blueprint, request

import calc
import const
import fields
from authz import ALL_ROLES, GROWER_MANAGER, body, guard
from envelope import created, ok, paginated, public
from errors import ApiError
from helpers import fetch, filter_equals, occ
from money import q2
from store import base_record, db, ordered, touch

bp = Blueprint("zones", __name__)


# ------------------------------------------------------------------ Zone


@bp.post("/zones")
@guard([GROWER_MANAGER])
def create_zone():
    payload = body()
    # priority 4 - presence, type and declared numeric bounds
    code = fields.string(payload, "code", min_len=1, max_len=16)
    area_sqft = fields.integer(payload, "area_sqft", lo=1000, hi=200000)
    glazing_type = fields.enum_slot(payload, "glazing_type")
    has_thermal_screen = fields.boolean(payload, "has_thermal_screen")
    has_supplemental_lighting = fields.boolean(payload, "has_supplemental_lighting")
    chp_connected = fields.boolean(payload, "chp_connected")
    hive_slot_capacity = fields.integer(payload, "hive_slot_capacity", lo=0, hi=40)
    labor_budget_usd = fields.number(payload, "labor_budget_usd", lo=0)
    # priority 5 - enum membership
    fields.enum_value(glazing_type, "glazing_type", const.GLAZING_TYPES)
    # priority 19 - natural key uniqueness
    for existing in db["zones"].values():
        if existing["code"] == code:
            raise ApiError("ERR_ZONE_CODE_DUPLICATE")

    budget = q2(labor_budget_usd)
    record = base_record()
    record.update({
        "code": code,
        "area_sqft": area_sqft,
        "glazing_type": glazing_type,
        "has_thermal_screen": has_thermal_screen,
        "has_supplemental_lighting": has_supplemental_lighting,
        "chp_connected": chp_connected,
        "hive_slot_capacity": hive_slot_capacity,
        "labor_budget_usd": budget,
        "status": "IDLE",
        "ipm_posture": "NORMAL",
        "irrigation_posture": "NORMAL",
        "open_pest_alert_count": 0,
        "drain_alarm_count": 0,
        "hive_slots_used": 0,
        "labor_budget_committed_usd": q2(0),
        "labor_budget_remaining_usd": budget,
        "reentry_clear_at": None,
        "climate_plan_revision": 0,
    })
    db["zones"][record["id"]] = record
    return created(public(record))


@bp.get("/zones")
@guard(ALL_ROLES)
def list_zones():
    rows = ordered("zones")
    rows = filter_equals(rows, "status", request.args.get("status"))
    rows = filter_equals(rows, "ipm_posture", request.args.get("ipm_posture"))
    rows = filter_equals(rows, "irrigation_posture", request.args.get("irrigation_posture"))
    return paginated(rows, public)


@bp.get("/zones/<zone_id>")
@guard(ALL_ROLES)
def get_zone(zone_id):
    return ok(public(fetch("zones", zone_id)))


@bp.post("/zones/<zone_id>/posture-overrides")
@guard([GROWER_MANAGER])
def override_posture(zone_id):
    payload = body()
    target_field = fields.enum_slot(payload, "target_field")
    target_value = fields.enum_slot(payload, "target_value")
    fields.string(payload, "override_reason", min_len=1)
    expected = fields.integer(payload, "expected_zone_version")
    fields.enum_value(target_field, "target_field", const.OVERRIDE_TARGET_FIELDS)
    if target_value != "NORMAL":
        raise ApiError("ERR_VALIDATION", "target_value must be NORMAL")
    zone = fetch("zones", zone_id)
    occ(zone, expected, "ERR_STALE_ZONE_VERSION")

    if target_field == "ipm_posture":
        zone["open_pest_alert_count"] = 0
        zone["reentry_clear_at"] = None
    else:
        # Clearing the irrigation alarm counter never clears the crop cycles'
        # nutrient_stress_flag, and never reinstates cancelled labor tasks.
        zone["drain_alarm_count"] = 0
    calc.refresh_zone(zone, force=True)
    return ok(public(zone))


# ------------------------------------------------------------------ Variety


@bp.post("/varieties")
@guard([GROWER_MANAGER])
def create_variety():
    payload = body()
    name = fields.string(payload, "name", min_len=1)
    crop_type = fields.enum_slot(payload, "crop_type")
    cycle_length_weeks = fields.integer(payload, "cycle_length_weeks", lo=4, hi=60)
    first_harvest_week = fields.integer(
        payload, "first_harvest_week", lo=2, hi=cycle_length_weeks
    )
    plant_density = fields.number(
        payload, "plant_density_per_sqft", lo=0, hi=2, exclusive_lo=True
    )
    curve = fields.number_list(payload, "yield_curve_lbs_per_sqft", lo=0)
    grade_a_ratio_pct = fields.number(payload, "grade_a_ratio_pct", lo=0, hi=100)
    requires_pollination = fields.boolean(payload, "requires_pollination")
    ec_target_ms = fields.number(payload, "ec_target_ms", lo=0, hi=6, exclusive_lo=True)
    fields.enum_value(crop_type, "crop_type", const.CROP_TYPES)
    # priority 21
    if len(curve) != cycle_length_weeks - first_harvest_week + 1:
        raise ApiError("ERR_YIELD_CURVE_LENGTH_MISMATCH")

    record = base_record(with_common=False)
    record.update({
        "name": name,
        "crop_type": crop_type,
        "cycle_length_weeks": cycle_length_weeks,
        "first_harvest_week": first_harvest_week,
        "plant_density_per_sqft": plant_density,
        "yield_curve_lbs_per_sqft": curve,
        "grade_a_ratio_pct": grade_a_ratio_pct,
        "requires_pollination": requires_pollination,
        "ec_target_ms": ec_target_ms,
    })
    db["varieties"][record["id"]] = record
    return created(public(record))


@bp.get("/varieties")
@guard(ALL_ROLES)
def list_varieties():
    rows = ordered("varieties")
    rows = filter_equals(rows, "crop_type", request.args.get("crop_type"))
    return paginated(rows, public)


@bp.get("/varieties/<variety_id>")
@guard(ALL_ROLES)
def get_variety(variety_id):
    return ok(public(fetch("varieties", variety_id)))
