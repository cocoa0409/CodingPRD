"""Harvest machines, cleanout certification and harvest events (PRD 3.4)."""

from flask import Blueprint

import calc
from common import (get_contract, get_equipment, get_harvest_event, get_variety,
                    paginate, public, public_list, rows_where)
from envelope import list_response, object_response
from errors import ApiError
from services import new_seed_lot
from store import db, new_record, touch
from validation import (EQUIPMENT_KINDS, Field, authenticate, bad_request, json_body,
                        parse_fields, parse_pagination, query_enum, query_string)

bp = Blueprint("harvest", __name__)

EQUIPMENT_STATUSES = ("AVAILABLE", "DIRTY", "OUT_OF_SERVICE")

EQUIPMENT_FIELDS = [
    Field("equipment_code", "string"),
    Field("equipment_kind", "enum", members=EQUIPMENT_KINDS),
    Field("cleanout_minutes_required", "integer", minimum=0),
]


@bp.post("/seed-ops/harvest-equipment")
def create_equipment():
    authenticate(("ProgramAdmin", "ConditioningManager"))
    data = parse_fields(json_body(), EQUIPMENT_FIELDS)
    for existing in db.harvest_equipment.values():
        if existing["equipment_code"] == data["equipment_code"]:
            bad_request("equipment_code must be unique across the fleet.")
    rec = new_record(True)
    rec["equipment_code"] = data["equipment_code"]
    rec["equipment_kind"] = data["equipment_kind"]
    rec["cleanout_minutes_required"] = data["cleanout_minutes_required"]
    rec["status"] = "DIRTY"
    rec["last_cleanout_at"] = None
    rec["last_cleanout_variety_id"] = None
    rec["cleanout_certified"] = False
    db.harvest_equipment[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.post("/seed-ops/harvest-equipment/<harvest_equipment_id>/cleanout-certification")
def certify_cleanout(harvest_equipment_id):
    authenticate(("ConditioningManager", "FieldOfficer"))
    data = parse_fields(json_body(), [Field("variety_id", "string"),
                                      Field("cleaned_at", "datetime")])
    equipment = get_equipment(harvest_equipment_id)
    variety = get_variety(data["variety_id"])
    if data["cleaned_at"] > db.now():
        raise ApiError("ERR_DATE_IN_FUTURE")

    equipment["status"] = "AVAILABLE"
    equipment["cleanout_certified"] = True
    equipment["last_cleanout_variety_id"] = variety["id"]
    equipment["last_cleanout_at"] = data["cleaned_at__raw"]
    touch(equipment)
    return object_response(public(equipment))


HARVEST_FIELDS = [
    Field("production_contract_id", "string"),
    Field("harvest_equipment_id", "string"),
    Field("window_start", "datetime"),
    Field("window_end", "datetime"),
    Field("gross_weight_kg", "number", exclusive_min=0),
    Field("moisture_pct", "number", minimum=0, maximum=40),
    Field("bag_size_kg", "number", required=False, exclusive_min=0, default=25.0),
]


@bp.post("/seed-ops/harvest-events")
def record_harvest():
    authenticate(("FieldOfficer", "ConditioningManager"))
    data = parse_fields(json_body(), HARVEST_FIELDS)
    contract = get_contract(data["production_contract_id"])
    equipment = get_equipment(data["harvest_equipment_id"])

    if contract["status"] not in ("INSPECTION_PASSED", "HARVESTED"):
        raise ApiError("ERR_INVALID_CONTRACT_STATE")
    if (equipment["status"] != "AVAILABLE"
            or not equipment["cleanout_certified"]
            or equipment["last_cleanout_variety_id"] != contract["variety_id"]):
        raise ApiError("ERR_EQUIPMENT_CLEANOUT_REQUIRED")
    if not data["window_start"] < data["window_end"]:
        raise ApiError("ERR_INVALID_WINDOW")

    for other in db.harvest_events.values():
        if other["harvest_equipment_id"] != equipment["id"]:
            continue
        if (data["window_start"] <= other["_window_end"]
                and other["_window_start"] <= data["window_end"]):
            raise ApiError("ERR_EQUIPMENT_WINDOW_CONFLICT")

    if data["window_end"] > db.now():
        raise ApiError("ERR_HARVEST_WINDOW_NOT_ELAPSED")

    variety = db.varieties[contract["variety_id"]]
    dockage, clean_kg, units = calc.provisional_harvest_basis(
        data["gross_weight_kg"], data["moisture_pct"],
        variety["estimated_conditioning_shrink_pct"])

    rec = new_record(False)
    rec["production_contract_id"] = contract["id"]
    rec["harvest_equipment_id"] = equipment["id"]
    rec["seed_lot_id"] = None
    rec["window_start"] = data["window_start__raw"]
    rec["window_end"] = data["window_end__raw"]
    rec["gross_weight_kg"] = data["gross_weight_kg"]
    rec["moisture_pct"] = data["moisture_pct"]
    rec["bag_size_kg"] = data["bag_size_kg"]
    rec["moisture_dockage_pct"] = dockage
    rec["provisional_clean_kg"] = clean_kg
    rec["provisional_clean_units"] = units
    rec["_window_start"] = data["window_start"]
    rec["_window_end"] = data["window_end"]
    db.harvest_events[rec["id"]] = rec

    lot = new_seed_lot(contract, contract["season_year"], contract["variety_id"],
                       data["gross_weight_kg"], data["bag_size_kg"],
                       data["moisture_pct"], units)
    rec["seed_lot_id"] = lot["id"]

    contract["provisional_clean_units_total"] = calc.round_half_up(
        calc.dec(contract["provisional_clean_units_total"]) + units, 2)
    if contract["status"] == "INSPECTION_PASSED":
        contract["status"] = "HARVESTED"
    touch(contract)

    equipment["status"] = "DIRTY"
    equipment["cleanout_certified"] = False
    touch(equipment)
    return object_response(public(rec), 201)


@bp.get("/seed-ops/harvest-equipment/<harvest_equipment_id>")
def read_equipment(harvest_equipment_id):
    authenticate(("ProgramAdmin", "FieldOfficer", "ConditioningManager"))
    return object_response(public(get_equipment(harvest_equipment_id)))


@bp.get("/seed-ops/harvest-equipment")
def list_equipment():
    authenticate(("ProgramAdmin", "FieldOfficer", "ConditioningManager"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.harvest_equipment,
        last_cleanout_variety_id=query_string("last_cleanout_variety_id"),
        status=query_enum("status", EQUIPMENT_STATUSES),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.get("/seed-ops/harvest-events/<harvest_event_id>")
def read_harvest_event(harvest_event_id):
    authenticate(("ProgramAdmin", "FieldOfficer", "ConditioningManager",
                  "SettlementAccountant", "Grower"))
    return object_response(public(get_harvest_event(harvest_event_id)))


@bp.get("/seed-ops/harvest-events")
def list_harvest_events():
    authenticate(("ProgramAdmin", "FieldOfficer", "ConditioningManager",
                  "SettlementAccountant", "Grower"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.harvest_events,
        production_contract_id=query_string("production_contract_id"),
        harvest_equipment_id=query_string("harvest_equipment_id"),
        seed_lot_id=query_string("seed_lot_id"),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)
