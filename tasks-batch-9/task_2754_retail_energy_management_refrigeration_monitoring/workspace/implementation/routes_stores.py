"""Store portfolio onboarding, reads and BMS commissioning (PRD 3.1, 3.2)."""

from decimal import Decimal

from flask import Blueprint

import cascade
import common
import derive
import envelope
import serial
import validate as v
from common import (BMS_STATUSES, CASE_TYPES, CLIMATE_ZONES, DR_ENROLLMENT_STATES,
                    ENERGY_POSTURES, EQUIPMENT_CLASSES, MEASURE_TYPES,
                    MONITORING_STATES, OVERRIDE_STATES, OVERRIDE_TYPES,
                    PRIORITY_BASES, PRODUCT_CLASSES, RETROFIT_STATES, SEVERITIES,
                    STORE_FORMATS, TARIFF_STATES, ZONES, FAULT_STATES)
from db import db, new_row, rows
from errors import ApiError
from security import (ENERGY_MANAGER, NON_GATEWAY_ROLES, ALL_ROLES, PLATFORM_ADMIN,
                      roles, require_store_scope)

bp = Blueprint("stores", __name__)

DEFAULT_BLENDED_RATE = Decimal("0.11")
DEFAULT_OVERRIDE_BUDGET_KWH = Decimal("500.00")
DEFAULT_LIGHTING_ON = "05:30"
DEFAULT_LIGHTING_OFF = "23:00"


def _time_of_day(body, name, default):
    value = v.get_str(body, name, required=False, default=None)
    if value is None:
        return default
    if not common.TIME_OF_DAY_RE.match(value):
        v.bad("field '%s' must be a 24-hour local time of day" % name)
    return value


@bp.route("/stores", methods=["POST"])
@roles(PLATFORM_ADMIN)
def create_store():
    body = v.body()
    code = v.get_str(body, "code", min_len=1, max_len=32)
    climate_zone = v.get_enum(body, "climate_zone", CLIMATE_ZONES)
    store_format = v.get_enum(body, "store_format", STORE_FORMATS)
    floor_area_sqft = v.get_int(body, "floor_area_sqft", min_=1)
    blended_rate = v.get_num(body, "blended_rate_usd_per_kwh", 4, required=False,
                             default=DEFAULT_BLENDED_RATE, gt=0)
    override_budget = v.get_num(body, "override_budget_kwh_month", 2, required=False,
                                default=DEFAULT_OVERRIDE_BUDGET_KWH, ge=0)
    lighting_on = _time_of_day(body, "lighting_on_time_local", DEFAULT_LIGHTING_ON)
    lighting_off = _time_of_day(body, "lighting_off_time_local", DEFAULT_LIGHTING_OFF)
    daylight = v.get_bool(body, "daylight_harvest_enabled", required=False, default=True)
    occupancy = v.get_bool(body, "occupancy_control_enabled", required=False, default=True)
    for existing in db.stores.values():
        if existing["code"] == code:
            v.bad("store code '%s' is already registered" % code)
    store = new_row(db.stores, {
        "code": code,
        "climate_zone": climate_zone,
        "store_format": store_format,
        "floor_area_sqft": floor_area_sqft,
        "blended_rate_usd_per_kwh": blended_rate,
        "bms_status": "NOT_DEPLOYED",
        "active_standard_id": None,
        "energy_posture": "NORMAL",
        "override_budget_kwh_month": override_budget,
        "lighting_on_time_local": lighting_on,
        "lighting_off_time_local": lighting_off,
        "daylight_harvest_enabled": daylight,
        "occupancy_control_enabled": occupancy,
    })
    return envelope.created(serial.store(store))


@bp.route("/stores", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def list_stores():
    limit, offset = v.query_pagination()
    climate_zone = v.query_enum("climate_zone", CLIMATE_ZONES)
    store_format = v.query_enum("store_format", STORE_FORMATS)
    energy_posture = v.query_enum("energy_posture", ENERGY_POSTURES)
    bms_status = v.query_enum("bms_status", BMS_STATUSES)
    active_standard_id = v.query_str("active_standard_id")
    outlier_flag = v.query_bool("benchmark_outlier_flag")
    items = rows(db.stores)
    items = common.apply_eq(items, "climate_zone", climate_zone)
    items = common.apply_eq(items, "store_format", store_format)
    items = common.apply_eq(items, "energy_posture", energy_posture)
    items = common.apply_eq(items, "bms_status", bms_status)
    items = common.apply_eq(items, "active_standard_id", active_standard_id)
    if outlier_flag is not None:
        import calc
        eui_map = serial._eui_map()
        items = [s for s in items
                 if calc.benchmark_for_store(s, eui_map)["benchmark_outlier_flag"]
                 == outlier_flag]
    return common.list_response(items, serial.store, limit, offset)


@bp.route("/stores/<store_id>", methods=["GET"])
@roles(*ALL_ROLES)
def get_store(store_id):
    store = common.get_store(store_id)
    require_store_scope(store_id)
    return envelope.ok(serial.store(store))


@bp.route("/stores/<store_id>/utility-accounts", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def list_store_accounts(store_id):
    limit, offset = v.query_pagination()
    tariff_state = v.query_enum("tariff_state", TARIFF_STATES)
    enrollment = v.query_enum("dr_enrollment_state", DR_ENROLLMENT_STATES)
    common.get_store(store_id)
    items = derive.store_accounts(store_id)
    items = common.apply_eq(items, "tariff_state", tariff_state)
    items = common.apply_eq(items, "dr_enrollment_state", enrollment)
    return common.list_response(items, serial.account, limit, offset)


@bp.route("/stores/<store_id>/refrigeration-cases", methods=["GET"])
@roles(*ALL_ROLES)
def list_store_cases(store_id):
    limit, offset = v.query_pagination()
    monitoring_state = v.query_enum("monitoring_state", MONITORING_STATES)
    case_type = v.query_enum("case_type", CASE_TYPES)
    product_class = v.query_enum("product_class", PRODUCT_CLASSES)
    common.get_store(store_id)
    items = derive.store_cases(store_id)
    items = common.apply_eq(items, "monitoring_state", monitoring_state)
    items = common.apply_eq(items, "case_type", case_type)
    items = common.apply_eq(items, "product_class", product_class)
    return common.list_response(items, serial.case, limit, offset)


@bp.route("/stores/<store_id>/lighting-overrides", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def list_store_overrides(store_id):
    limit, offset = v.query_pagination()
    state = v.query_enum("state", OVERRIDE_STATES)
    zone = v.query_enum("zone", ZONES)
    override_type = v.query_enum("override_type", OVERRIDE_TYPES)
    common.get_store(store_id)
    items = derive.store_overrides(store_id)
    items = common.apply_eq(items, "state", state)
    items = common.apply_eq(items, "zone", zone)
    items = common.apply_eq(items, "override_type", override_type)
    return common.list_response(items, serial.override, limit, offset)


@bp.route("/stores/<store_id>/fault-diagnostics", methods=["GET"])
@roles(*ALL_ROLES)
def list_store_faults(store_id):
    limit, offset = v.query_pagination()
    state = v.query_enum("state", FAULT_STATES)
    equipment_class = v.query_enum("equipment_class", EQUIPMENT_CLASSES)
    severity = v.query_enum("severity", SEVERITIES)
    common.get_store(store_id)
    items = derive.store_faults(store_id)
    items = common.apply_eq(items, "state", state)
    items = common.apply_eq(items, "equipment_class", equipment_class)
    items = common.apply_eq(items, "severity", severity)
    return common.list_response(items, serial.fault, limit, offset)


@bp.route("/stores/<store_id>/retrofit-projects", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def list_store_retrofits(store_id):
    limit, offset = v.query_pagination()
    state = v.query_enum("state", RETROFIT_STATES)
    measure_type = v.query_enum("measure_type", MEASURE_TYPES)
    priority_basis = v.query_enum("priority_basis", PRIORITY_BASES)
    escalated = v.query_bool("escalated_review")
    common.get_store(store_id)
    items = derive.store_retrofits(store_id)
    items = common.apply_eq(items, "state", state)
    items = common.apply_eq(items, "measure_type", measure_type)
    items = common.apply_eq(items, "priority_basis", priority_basis)
    if escalated is not None:
        items = [p for p in items if p["escalated_review"] == escalated]
    return common.list_response(items, serial.retrofit, limit, offset)


# ------------------------------------------------------- BMS commissioning ----

@bp.route("/stores/<store_id>/bms-commissioning", methods=["POST"])
@roles(ENERGY_MANAGER)
def commission_bms(store_id):
    body = v.body()
    standard_id = v.get_str(body, "standard_id")
    expected_version = v.get_int(body, "expected_store_version")
    store = common.get_store(store_id)
    standard = common.get_standard(standard_id)
    if store["bms_status"] == "COMMISSIONING":
        raise ApiError("ERR_BMS_STATE_INVALID")
    if expected_version != store["version"]:
        raise ApiError("ERR_STALE_STORE_VERSION")
    if store["energy_posture"] == "LOCKED":
        raise ApiError("ERR_FOOD_SAFETY_HOLD")
    if standard["status"] != "PUBLISHED":
        raise ApiError("ERR_STANDARD_NOT_PUBLISHED")
    if (standard["climate_zone"] != store["climate_zone"]
            or standard["store_format"] != store["store_format"]):
        raise ApiError("ERR_STANDARD_SCOPE_MISMATCH")
    store["bms_status"] = "COMMISSIONING"
    store["active_standard_id"] = standard_id
    cascade.touch(store)
    return envelope.ok(serial.store(store))


@bp.route("/stores/<store_id>/bms-activation", methods=["POST"])
@roles(ENERGY_MANAGER)
def activate_bms(store_id):
    store = common.get_store(store_id)
    if store["bms_status"] != "COMMISSIONING":
        raise ApiError("ERR_BMS_STATE_INVALID")
    standard = db.standards.get(store["active_standard_id"])
    if standard is None or standard["status"] != "PUBLISHED":
        raise ApiError("ERR_STANDARD_NOT_PUBLISHED")
    store["bms_status"] = "ACTIVE"
    cascade.touch(store)
    cascade.recompute_posture(store)
    return envelope.ok(serial.store(store))
