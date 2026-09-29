"""Logical clock, base buildings and floor plates (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import clock
import constants
import db
import helpers
import queries
import response
import serializers
import validation
from errors import fail
from util import fmt_iso, num

bp = Blueprint("core", __name__)

ZERO = Decimal("0.00")


# ------------------------------------------------------------------ logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    body = validation.body()
    moment = validation.req_dt(body, "current_utc")
    auth.require(*constants.ALL_ROLES)
    clock.set_now(moment)
    return response.ok({"current_utc": fmt_iso(clock.now())})


# ----------------------------------------------------------------------- buildings
@bp.post("/buildings")
def create_building():
    body = validation.body()
    fields = {
        "name": validation.req_str(body, "name"),
        "address_city": validation.req_str(body, "address_city"),
        "occupancy_status": validation.req_enum(body, "occupancy_status", constants.OCCUPANCY_STATUSES),
        "published_floor_to_floor_ft": validation.req_num(body, "published_floor_to_floor_ft", gt=0),
        "published_live_load_psf": validation.req_num(body, "published_live_load_psf", gt=0),
        "published_vibration_class": validation.req_enum(body, "published_vibration_class", constants.VIBRATION_CLASSES),
        "exhaust_riser_capacity_cfm": validation.req_num(body, "exhaust_riser_capacity_cfm", ge=0),
        "emergency_power_capacity_kw": validation.req_num(body, "emergency_power_capacity_kw", ge=0),
        "chilled_water_capacity_tons": validation.req_num(body, "chilled_water_capacity_tons", ge=0),
        "suitability_state": "DRAFT",
        "latest_assessment_verdict": None,
    }
    auth.require(constants.ROLE_LANDLORD)
    record = db.create(db.buildings, fields)
    return response.created(serializers.building(record))


@bp.get("/buildings/<building_id>")
def get_building(building_id):
    auth.require(*constants.ALL_ROLES)
    building = helpers.fetch(db.buildings, building_id, "ERR_BUILDING_NOT_FOUND")
    return response.ok(serializers.building(building))


@bp.post("/buildings/<building_id>/conversion-approval")
def approve_conversion(building_id):
    auth.require(constants.ROLE_LANDLORD)
    building = helpers.fetch(db.buildings, building_id, "ERR_BUILDING_NOT_FOUND")
    if building["suitability_state"] not in ("ASSESSED_SUITABLE", "ASSESSED_CONDITIONAL"):
        fail("ERR_INVALID_BUILDING_STATE")
    if queries.lab_exhaust_item(building["id"]) is None:
        fail("ERR_CONVERSION_SCOPE_INCOMPLETE")
    building["suitability_state"] = "CONVERSION_APPROVED"
    db.touch(building)
    return response.ok(serializers.building(building))


# -------------------------------------------------------------------------- floors
@bp.post("/buildings/<building_id>/floors")
def create_floor(building_id):
    body = validation.body()
    fields = {
        "floor_number": validation.req_int(body, "floor_number", ge=1),
        "floor_to_floor_ft": validation.req_num(body, "floor_to_floor_ft", gt=0),
        "live_load_psf": validation.req_num(body, "live_load_psf", gt=0),
        "vibration_class": validation.req_enum(body, "vibration_class", constants.VIBRATION_CLASSES),
        "sprinklered": validation.opt_bool(body, "sprinklered", True),
    }
    auth.require(constants.ROLE_ENGINEER)
    building = helpers.fetch(db.buildings, building_id, "ERR_BUILDING_NOT_FOUND")
    for existing in queries.floors_of(building["id"]):
        if existing["floor_number"] == fields["floor_number"]:
            fail("ERR_DUPLICATE_FLOOR_NUMBER")
    fields["building_id"] = building["id"]
    record = db.create(db.floors, fields)
    return response.created(serializers.floor(record))


@bp.get("/buildings/<building_id>/floors")
def list_building_floors(building_id):
    limit, offset = validation.pagination()
    auth.require(*constants.ALL_ROLES)
    building = helpers.fetch(db.buildings, building_id, "ERR_BUILDING_NOT_FOUND")
    return helpers.page(queries.floors_of(building["id"]), serializers.floor, limit, offset)


@bp.get("/floors/<floor_id>")
def get_floor(floor_id):
    auth.require(*constants.ALL_ROLES)
    floor = helpers.fetch(db.floors, floor_id, "ERR_FLOOR_NOT_FOUND")
    return response.ok(serializers.floor(floor))


@bp.get("/floors")
def list_floors():
    limit, offset = validation.pagination()
    filters = {
        "building_id": validation.query_str("building_id"),
        "vibration_class": validation.query_enum("vibration_class", constants.VIBRATION_CLASSES),
    }
    auth.require(*constants.ALL_ROLES)
    records = helpers.filtered(db.ordered(db.floors.values()), filters)
    return helpers.page(records, serializers.floor, limit, offset)


@bp.get("/floors/<floor_id>/hazmat-utilization")
def floor_hazmat_utilization(floor_id):
    hazard_class = validation.query_enum("hazard_class", constants.HAZARD_CLASSES)
    if hazard_class is None:
        fail("ERR_VALIDATION", "hazard_class is required")
    control_area_index = validation.query_int("control_area_index")
    if control_area_index is None:
        control_area_index = 1
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_AHJ)
    floor = helpers.fetch(db.floors, floor_id, "ERR_FLOOR_NOT_FOUND")
    allowed = calc.control_areas_allowed(floor)
    if control_area_index < 1 or control_area_index > allowed:
        fail("ERR_CONTROL_AREA_OUT_OF_RANGE")
    report = calc.hazmat_utilization(floor, hazard_class, control_area_index)
    payload = {}
    for key, value in report.items():
        payload[key] = value if isinstance(value, (str, int)) else num(value)
    payload["control_area_index"] = control_area_index
    payload["control_areas_allowed"] = allowed
    return response.ok(payload)
