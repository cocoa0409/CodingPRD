"""Suitability assessments and conversion scope items (PRD 3.2)."""
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

bp = Blueprint("assessments", __name__)

VERDICT_STATE = {
    "SUITABLE": "ASSESSED_SUITABLE",
    "SUITABLE_WITH_CONVERSION": "ASSESSED_CONDITIONAL",
    "UNSUITABLE": "ASSESSED_UNSUITABLE",
}
ALL_DISCIPLINES = sorted(constants.DISCIPLINES)


# ------------------------------------------------------------------- assessments
@bp.post("/buildings/<building_id>/suitability-assessments")
def open_assessment(building_id):
    body = validation.body()
    fields = {
        "assessment_basis": validation.req_enum(body, "assessment_basis", constants.ASSESSMENT_BASES),
        "required_vibration_class": validation.req_enum(body, "required_vibration_class", constants.VIBRATION_CLASSES),
        "required_exhaust_cfm": validation.req_num(body, "required_exhaust_cfm", gt=0),
        "required_power_kw": validation.req_num(body, "required_power_kw", gt=0),
        "measured_floor_to_floor_ft": validation.opt_num(body, "measured_floor_to_floor_ft", gt=0),
        "measured_live_load_psf": validation.opt_num(body, "measured_live_load_psf", gt=0),
        "measured_vibration_class": validation.opt_enum(body, "measured_vibration_class", constants.VIBRATION_CLASSES),
    }
    auth.require(constants.ROLE_ENGINEER)
    building = helpers.fetch(db.buildings, building_id, "ERR_BUILDING_NOT_FOUND")

    for existing in queries.assessments_of(building["id"]):
        if existing["status"] in ("DRAFT", "SUBMITTED"):
            fail("ERR_ASSESSMENT_ALREADY_OPEN")
    if building["suitability_state"] in ("CONVERSION_APPROVED", "CONVERSION_COMPLETE"):
        fail("ERR_INVALID_BUILDING_STATE")

    fields.update({
        "building_id": building["id"],
        "height_credit": 0,
        "structural_credit": 0,
        "vibration_credit": 0,
        "utility_credit": 0,
        "utility_headroom_ratio": Decimal("0.0000"),
        "suitability_score": Decimal("0.0"),
        "hard_fail_capped": False,
        "verdict": None,
        "status": "DRAFT",
        "decided_by_user_id": None,
        "return_note": None,
    })
    record = db.create(db.assessments, fields)
    building["suitability_state"] = "ASSESSING"
    db.touch(building)
    return response.created(serializers.assessment(record))


@bp.get("/buildings/<building_id>/suitability-assessments")
def list_building_assessments(building_id):
    limit, offset = validation.pagination()
    status = validation.query_enum("status", constants.ASSESSMENT_STATUSES)
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_AHJ)
    building = helpers.fetch(db.buildings, building_id, "ERR_BUILDING_NOT_FOUND")
    records = helpers.filtered(queries.assessments_of(building["id"]), {"status": status})
    return helpers.page(records, serializers.assessment, limit, offset)


@bp.get("/suitability-assessments/<assessment_id>")
def get_assessment(assessment_id):
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_AHJ)
    record = helpers.fetch(db.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    return response.ok(serializers.assessment(record))


@bp.get("/suitability-assessments")
def list_assessments():
    limit, offset = validation.pagination()
    filters = {
        "building_id": validation.query_str("building_id"),
        "assessment_basis": validation.query_enum("assessment_basis", constants.ASSESSMENT_BASES),
        "status": validation.query_enum("status", constants.ASSESSMENT_STATUSES),
        "verdict": validation.query_enum("verdict", constants.VERDICTS),
    }
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_AHJ)
    records = helpers.filtered(db.ordered(db.assessments.values()), filters)
    return helpers.page(records, serializers.assessment, limit, offset)


@bp.post("/suitability-assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    auth.require(constants.ROLE_ENGINEER)
    record = helpers.fetch(db.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    if record["status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_INVALID_ASSESSMENT_STATE")
    building = db.buildings.get(record["building_id"])
    record.update(calc.score_assessment(record, building))
    record["status"] = "SUBMITTED"
    record["return_note"] = None
    db.touch(record)
    return response.ok(serializers.assessment(record))


@bp.post("/suitability-assessments/<assessment_id>/decision")
def decide_assessment(assessment_id):
    body = validation.body()
    decision = validation.req_enum(body, "decision", ["ACCEPT", "RETURN"])
    return_note = validation.raw_opt_str(body, "return_note")
    user_id, _role = auth.require(constants.ROLE_LANDLORD)
    record = helpers.fetch(db.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")

    if record["status"] != "SUBMITTED":
        fail("ERR_INVALID_ASSESSMENT_STATE")
    if decision == "RETURN" and helpers.blank(return_note):
        fail("ERR_RETURN_NOTE_REQUIRED")

    record["decided_by_user_id"] = user_id
    if decision == "RETURN":
        record["return_note"] = return_note
        record["status"] = "RETURNED"
        db.touch(record)
        return response.ok(serializers.assessment(record))

    record["status"] = "ACCEPTED"
    db.touch(record)
    building = db.buildings.get(record["building_id"])
    if building is not None:
        building["latest_assessment_verdict"] = record["verdict"]
        building["suitability_state"] = VERDICT_STATE[record["verdict"]]
        db.touch(building)
    return response.ok(serializers.assessment(record))


# ------------------------------------------------------------- conversion scope
@bp.post("/buildings/<building_id>/conversion-scope-items")
def create_scope_item(building_id):
    body = validation.body()
    fields = {
        "discipline": validation.req_enum(body, "discipline", constants.DISCIPLINES),
        "description": validation.req_str(body, "description"),
        "budget_usd": validation.req_num(body, "budget_usd", ge=0),
        "capacity_delta_cfm": validation.opt_num(body, "capacity_delta_cfm", Decimal("0.00"), ge=0),
        "capacity_delta_kw": validation.opt_num(body, "capacity_delta_kw", Decimal("0.00"), ge=0),
    }
    auth.require(constants.ROLE_LANDLORD)
    building = helpers.fetch(db.buildings, building_id, "ERR_BUILDING_NOT_FOUND")
    for existing in queries.scope_items_of(building["id"]):
        if existing["discipline"] == fields["discipline"]:
            fail("ERR_DUPLICATE_SCOPE_DISCIPLINE")
    fields.update({
        "building_id": building["id"],
        "status": "PLANNED",
        "completed_at": None,
    })
    record = db.create(db.scope_items, fields)
    db.touch(building)
    return response.created(serializers.scope_item(record))


@bp.get("/buildings/<building_id>/conversion-scope-items")
def list_building_scope_items(building_id):
    limit, offset = validation.pagination()
    status = validation.query_enum("status", constants.SCOPE_ITEM_STATUSES)
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_AHJ)
    building = helpers.fetch(db.buildings, building_id, "ERR_BUILDING_NOT_FOUND")
    records = helpers.filtered(queries.scope_items_of(building["id"]), {"status": status})
    return helpers.page(records, serializers.scope_item, limit, offset)


@bp.get("/conversion-scope-items/<item_id>")
def get_scope_item(item_id):
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_AHJ)
    record = helpers.fetch(db.scope_items, item_id, "ERR_SCOPE_ITEM_NOT_FOUND")
    return response.ok(serializers.scope_item(record))


@bp.get("/conversion-scope-items")
def list_scope_items():
    limit, offset = validation.pagination()
    filters = {
        "building_id": validation.query_str("building_id"),
        "discipline": validation.query_enum("discipline", constants.DISCIPLINES),
        "status": validation.query_enum("status", constants.SCOPE_ITEM_STATUSES),
    }
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_AHJ)
    records = helpers.filtered(db.ordered(db.scope_items.values()), filters)
    return helpers.page(records, serializers.scope_item, limit, offset)


@bp.post("/conversion-scope-items/<item_id>/complete")
def complete_scope_item(item_id):
    auth.require(constants.ROLE_ENGINEER)
    record = helpers.fetch(db.scope_items, item_id, "ERR_SCOPE_ITEM_NOT_FOUND")
    building = db.buildings.get(record["building_id"])
    if building is None or building["suitability_state"] != "CONVERSION_APPROVED":
        fail("ERR_BUILDING_NOT_CONVERSION_APPROVED")
    if record["status"] == "COMPLETE":
        fail("ERR_INVALID_SCOPE_ITEM_STATE")

    record["status"] = "COMPLETE"
    record["completed_at"] = clock.now()
    db.touch(record)

    covered, complete = calc.scope_discipline_lists(building)
    if covered == complete and complete == ALL_DISCIPLINES:
        building["suitability_state"] = "CONVERSION_COMPLETE"
    db.touch(building)
    return response.ok(serializers.scope_item(record))
