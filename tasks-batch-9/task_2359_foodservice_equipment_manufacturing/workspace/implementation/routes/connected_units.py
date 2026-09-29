"""ConnectedUnit endpoints (PRD Sections 3.8, 3.9)."""
from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from errors import ApiError
from middleware import authorize
from response import ok, created, ok_list
from routes.helpers import find, filter_by, require_reason
from services import calc, derive
from timeutil import add_days

bp = Blueprint("connected_units", __name__)

PROGRAM_STATUSES = ("PENDING_INSTALL", "ACTIVE", "EXTENDED", "GRACE", "EXPIRED", "VOIDED")
READ_ROLES = ("ConnectedOpsEngineer", "WarrantyAdjudicator", "ServicePartnerUser", "ChainAdmin",
              "PlatformAdmin")


@bp.post("/connected-units")
def register_unit():
    authorize("ConnectedOpsEngineer", "PlatformAdmin")
    payload = validate.body()
    equipment_model_id = validate.string_field(payload, "equipment_model_id")
    serial_number = validate.string_field(payload, "serial_number", min_len=1, max_len=64)
    service_tier = validate.enum_field(payload, "service_tier", calc.SERVICE_TIERS)
    site_order_id = validate.string_field(payload, "site_order_id", required=False, nullable=True)

    find(db.equipment_models, equipment_model_id, "ERR_EQUIPMENT_MODEL_NOT_FOUND")
    if site_order_id is not None:
        find(db.site_orders, site_order_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")

    for other in db.connected_units.values():
        if other["serial_number"] == serial_number:
            raise ApiError("ERR_DUPLICATE_SERIAL_NUMBER", "the serial number is already in use")

    unit = insert(db.connected_units, {
        "equipment_model_id": equipment_model_id,
        "site_order_id": site_order_id,
        "serial_number": serial_number,
        "service_tier": service_tier,
        "firmware_version": calc.INITIAL_FIRMWARE_VERSION,
        "recipe_book_version": 1,
        "fault_count_30d": 0,
        "missed_heartbeat_count": 0,
        "health_score": 100,
        "service_program_status": "PENDING_INSTALL",
        "coverage_start_date": None,
        "coverage_end_date": None,
        "grace_expires_on": None,
        "reserve_initial_cents": 0,
        "reserve_balance_cents": 0,
        "claims_paid_cents": 0,
    })
    unit["health_score"] = derive.compute_health_score(unit)
    return created(unit)


@bp.get("/connected-units")
def list_units():
    authorize(*READ_ROLES)
    limit, offset = validate.pagination()
    equipment_model_id = validate.str_arg("equipment_model_id")
    site_order_id = validate.str_arg("site_order_id")
    service_program_status = validate.enum_arg("service_program_status", PROGRAM_STATUSES)

    items = ordered(db.connected_units)
    for unit in items:  # reading a unit re-evaluates its lazy expiry
        derive.refresh_unit_coverage(unit)
    items = filter_by(items, "equipment_model_id", equipment_model_id)
    items = filter_by(items, "site_order_id", site_order_id)
    items = filter_by(items, "service_program_status", service_program_status)
    return ok_list(items, limit, offset)


@bp.get("/connected-units/<unit_id>")
def get_unit(unit_id):
    authorize(*READ_ROLES)
    unit = find(db.connected_units, unit_id, "ERR_CONNECTED_RESOURCE_NOT_FOUND")
    derive.refresh_unit_coverage(unit)
    return ok(unit)


@bp.post("/connected-units/<unit_id>/telemetry")
def post_telemetry(unit_id):
    authorize("ConnectedOpsEngineer", "PlatformAdmin")
    payload = validate.body()
    fault_count_30d = validate.int_field(payload, "fault_count_30d", minimum=0)
    missed_heartbeat_count = validate.int_field(payload, "missed_heartbeat_count", minimum=0)

    unit = find(db.connected_units, unit_id, "ERR_CONNECTED_RESOURCE_NOT_FOUND")
    derive.refresh_unit_coverage(unit)

    unit["fault_count_30d"] = fault_count_30d
    unit["missed_heartbeat_count"] = missed_heartbeat_count
    unit["health_score"] = derive.compute_health_score(unit)
    touch(unit)
    return ok(unit)


@bp.post("/connected-units/<unit_id>/recipe-pushes")
def push_recipe(unit_id):
    authorize("ConnectedOpsEngineer", "PlatformAdmin")
    payload = validate.body()
    recipe_book_version = validate.int_field(payload, "recipe_book_version", minimum=1)

    unit = find(db.connected_units, unit_id, "ERR_CONNECTED_RESOURCE_NOT_FOUND")
    derive.refresh_unit_coverage(unit)

    if unit["service_program_status"] not in ("ACTIVE", "EXTENDED"):
        raise ApiError("ERR_CONNECTED_STATE_INVALID",
                       "a %s unit cannot receive a recipe push"
                       % unit["service_program_status"])

    unit["recipe_book_version"] = recipe_book_version
    touch(unit)
    return ok(unit)


@bp.post("/connected-units/<unit_id>/coverage-actions")
def coverage_action(unit_id):
    authorize("WarrantyAdjudicator", "PlatformAdmin")
    payload = validate.body()
    action = validate.enum_field(payload, "action", ("ACTIVATE", "EXTEND", "VOID"))
    void_reason = None
    if action == "VOID":
        void_reason = require_reason(payload, "void_reason")

    unit = find(db.connected_units, unit_id, "ERR_CONNECTED_RESOURCE_NOT_FOUND")
    derive.refresh_unit_coverage(unit)
    status = unit["service_program_status"]

    if action == "ACTIVATE":
        if status != "PENDING_INSTALL":
            raise ApiError("ERR_CONNECTED_STATE_INVALID",
                           "coverage cannot be activated from %s" % status)
        model = db.equipment_models[unit["equipment_model_id"]]
        if model["certification_posture"] not in ("LISTED", "PARTIAL"):
            raise ApiError("ERR_MODEL_LISTING_SUSPENDED",
                           "the model's certification posture is %s"
                           % model["certification_posture"])
        tier = unit["service_tier"]
        unit["service_program_status"] = "ACTIVE"
        unit["coverage_start_date"] = db.clock
        unit["coverage_end_date"] = add_days(db.clock, calc.COVERAGE_TERM_DAYS[tier])
        unit["reserve_initial_cents"] = calc.RESERVE_BY_TIER[tier]
        unit["reserve_balance_cents"] = calc.RESERVE_BY_TIER[tier]
        unit["claims_paid_cents"] = 0
    elif action == "EXTEND":
        if status != "ACTIVE":
            raise ApiError("ERR_CONNECTED_STATE_INVALID",
                           "coverage cannot be extended from %s" % status)
        if unit["service_tier"] != "EXTENDED_PLUS":
            raise ApiError("ERR_CONNECTED_STATE_INVALID",
                           "only an EXTENDED_PLUS unit can be extended")
        if unit["coverage_end_date"] is None or not db.clock < unit["coverage_end_date"]:
            raise ApiError("ERR_CONNECTED_STATE_INVALID", "the coverage term has already elapsed")
        unit["service_program_status"] = "EXTENDED"
        unit["coverage_end_date"] = add_days(unit["coverage_end_date"], calc.EXTENSION_TERM_DAYS)
        unit["reserve_initial_cents"] += calc.EXTENSION_RESERVE_CENTS
        unit["reserve_balance_cents"] += calc.EXTENSION_RESERVE_CENTS
    else:  # VOID
        if status not in ("ACTIVE", "EXTENDED", "GRACE"):
            raise ApiError("ERR_CONNECTED_STATE_INVALID",
                           "coverage cannot be voided from %s" % status)
        unit["service_program_status"] = "VOIDED"
        unit["reserve_balance_cents"] = 0

    touch(unit)
    return ok(unit)
