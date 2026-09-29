"""Field inspections, the rogueing loop and the grower-standing cascade
(PRD 3.3)."""

from flask import Blueprint

import calc
from common import get_contract, get_inspection, paginate, public, public_list, rows_where
from envelope import list_response, object_response
from errors import ApiError
from services import grower_standing_cascade
from store import db, new_record, touch
from validation import (Field, authenticate, bad_request, json_body, parse_fields,
                        parse_pagination, query_enum, query_string)

bp = Blueprint("inspections", __name__)

INSPECTION_STATUSES = ("RECORDED", "ROGUEING_DECLARED", "ROGUEING_VERIFIED", "CLOSED")

INSPECTION_FIELDS = [
    Field("production_contract_id", "string"),
    Field("inspected_on", "date"),
    Field("sampled_plants", "integer", exclusive_min=0),
    Field("off_type_plants", "integer", minimum=0),
    Field("restricted_weed_plants", "integer", minimum=0),
    Field("diseased_plants", "integer", minimum=0),
    Field("isolation_verified_m", "number"),
]


@bp.post("/seed-ops/field-inspections")
def record_inspection():
    user_id, _role = authenticate(("FieldOfficer",))
    data = parse_fields(json_body(), INSPECTION_FIELDS)
    contract = get_contract(data["production_contract_id"])

    planted = contract.get("_planted_on_date")
    if planted is not None and data["inspected_on"] < planted:
        bad_request("inspected_on may not precede the contract's planted_on date.")
    if contract["status"] != "PLANTED":
        raise ApiError("ERR_INVALID_CONTRACT_STATE")
    if data["inspected_on"] > db.today():
        raise ApiError("ERR_DATE_IN_FUTURE")

    same_day = [i for i in db.field_inspections.values()
                if i["inspector_user_id"] == user_id
                and i.get("_inspected_on_date") == data["inspected_on"]]
    if len(same_day) >= calc.INSPECTOR_DAILY_CAPACITY:
        raise ApiError("ERR_INSPECTOR_DAY_CAPACITY_EXCEEDED")

    variety = db.varieties[contract["variety_id"]]
    off_rate, weed_rate, disease_pct = calc.inspection_rates(
        data["sampled_plants"], data["off_type_plants"],
        data["restricted_weed_plants"], data["diseased_plants"])
    outcome = calc.inspection_outcome(off_rate, weed_rate, disease_pct,
                                      data["isolation_verified_m"], variety,
                                      contract["rogueing_rounds_used"])

    rec = new_record(True)
    rec["production_contract_id"] = contract["id"]
    rec["inspector_user_id"] = user_id
    rec["inspection_round"] = contract["inspection_round"] + 1
    rec["inspected_on"] = data["inspected_on__raw"]
    rec["_inspected_on_date"] = data["inspected_on"]
    rec["sampled_plants"] = data["sampled_plants"]
    rec["off_type_plants"] = data["off_type_plants"]
    rec["restricted_weed_plants"] = data["restricted_weed_plants"]
    rec["diseased_plants"] = data["diseased_plants"]
    rec["isolation_verified_m"] = data["isolation_verified_m"]
    rec["off_type_rate_per_10000"] = off_rate
    rec["weed_rate_per_10000"] = weed_rate
    rec["disease_incidence_pct"] = disease_pct
    rec["outcome"] = outcome
    rec["status"] = "RECORDED"
    rec["rogueing_plants_removed"] = None
    rec["rogueing_declared_on"] = None
    rec["rogueing_verified_by_user_id"] = None
    rec["verified_remaining_off_type_plants"] = None
    db.field_inspections[rec["id"]] = rec

    contract["inspection_round"] = contract["inspection_round"] + 1
    if outcome == "PASSED":
        contract["status"] = "INSPECTION_PASSED"
        touch(contract)
    elif outcome == "ROGUEING_ORDERED":
        contract["status"] = "ROGUEING_REQUIRED"
        contract["rogueing_rounds_used"] = contract["rogueing_rounds_used"] + 1
        touch(contract)
        grower_standing_cascade(db.growers[contract["grower_id"]], contract["id"])
    else:
        contract["status"] = "REJECTED"
        touch(contract)
        rec["status"] = "CLOSED"
        grower_standing_cascade(db.growers[contract["grower_id"]], contract["id"])
    return object_response(public(rec), 201)


DECLARATION_FIELDS = [
    Field("rogueing_plants_removed", "integer", minimum=0),
    Field("rogueing_declared_on", "date"),
]


@bp.post("/seed-ops/field-inspections/<field_inspection_id>/rogueing-declaration")
def declare_rogueing(field_inspection_id):
    user_id, _role = authenticate(("Grower",))
    data = parse_fields(json_body(), DECLARATION_FIELDS)
    inspection = get_inspection(field_inspection_id)
    contract = db.production_contracts[inspection["production_contract_id"]]
    if user_id != contract["grower_id"]:
        raise ApiError("ERR_GROWER_SCOPE_VIOLATION")
    if inspection["outcome"] != "ROGUEING_ORDERED" or inspection["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_INSPECTION_STATE")
    if data["rogueing_declared_on"] > db.today():
        raise ApiError("ERR_DATE_IN_FUTURE")

    inspection["rogueing_plants_removed"] = data["rogueing_plants_removed"]
    inspection["rogueing_declared_on"] = data["rogueing_declared_on__raw"]
    inspection["status"] = "ROGUEING_DECLARED"
    touch(inspection)
    return object_response(public(inspection))


@bp.post("/seed-ops/field-inspections/<field_inspection_id>/rogueing-verification")
def verify_rogueing(field_inspection_id):
    user_id, _role = authenticate(("FieldOfficer",))
    data = parse_fields(json_body(),
                        [Field("verified_remaining_off_type_plants", "integer", minimum=0)])
    inspection = get_inspection(field_inspection_id)

    if (inspection["outcome"] != "ROGUEING_ORDERED"
            or inspection["status"] == "ROGUEING_VERIFIED"):
        raise ApiError("ERR_INVALID_INSPECTION_STATE")
    if user_id == inspection["inspector_user_id"]:
        raise ApiError("ERR_SOD_ROGUEING_SELF_VERIFICATION")
    if inspection["status"] != "ROGUEING_DECLARED":
        raise ApiError("ERR_ROGUEING_NOT_DECLARED")

    contract = db.production_contracts[inspection["production_contract_id"]]
    variety = db.varieties[contract["variety_id"]]
    remaining_rate = calc.round_half_up(
        calc.dec(data["verified_remaining_off_type_plants"])
        / calc.dec(inspection["sampled_plants"]) * calc.dec(10000), 2)

    accepted = (remaining_rate <= calc.dec(variety["max_off_type_per_10000"])
                and contract["rogueing_rounds_used"] <= variety["max_rogueing_rounds"])

    inspection["verified_remaining_off_type_plants"] = data["verified_remaining_off_type_plants"]
    inspection["rogueing_verified_by_user_id"] = user_id
    if accepted:
        inspection["status"] = "ROGUEING_VERIFIED"
        touch(inspection)
        if contract["status"] == "ROGUEING_REQUIRED":
            contract["status"] = "PLANTED"
        touch(contract)
    else:
        inspection["status"] = "CLOSED"
        touch(inspection)
        if contract["status"] == "ROGUEING_REQUIRED":
            contract["status"] = "REJECTED"
        touch(contract)
        grower_standing_cascade(db.growers[contract["grower_id"]], contract["id"])
    return object_response(public(inspection))


@bp.get("/seed-ops/field-inspections/<field_inspection_id>")
def read_inspection(field_inspection_id):
    authenticate(("ProgramAdmin", "FieldOfficer", "Grower"))
    return object_response(public(get_inspection(field_inspection_id)))


@bp.get("/seed-ops/field-inspections")
def list_inspections():
    authenticate(("ProgramAdmin", "FieldOfficer", "Grower"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.field_inspections,
        production_contract_id=query_string("production_contract_id"),
        inspector_user_id=query_string("inspector_user_id"),
        inspected_on=query_string("inspected_on"),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)
