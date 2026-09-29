"""Production contracts: drafting, the offer compliance gate, signing and
cancellation (PRD 3.2, 3.3)."""

from flask import Blueprint

import calc
from common import (get_contract, get_field, get_grower, get_variety, paginate,
                    public, public_list, rows_where)
from envelope import list_response, object_response
from errors import ApiError
from routes.reference import assess_field
from services import close_open_inspections
from store import db, new_record, touch
from validation import (CONTRACT_CLASSES, Field, authenticate, json_body,
                        parse_fields, parse_pagination, query_enum, query_integer,
                        query_string)

bp = Blueprint("contracts", __name__)

CONTRACT_STATUSES = ("DRAFT", "OFFERED", "PLANTED", "ROGUEING_REQUIRED",
                     "INSPECTION_PASSED", "HARVESTED", "SETTLED", "CLOSED",
                     "REJECTED", "CANCELLED")

OCCUPYING_STATUSES = ("OFFERED", "PLANTED", "ROGUEING_REQUIRED", "INSPECTION_PASSED",
                      "HARVESTED", "SETTLED", "CLOSED")

CONTRACT_FIELDS = [
    Field("grower_id", "string"),
    Field("variety_id", "string"),
    Field("production_field_id", "string"),
    Field("season_year", "integer", minimum=2000, maximum=2100),
    Field("seed_class", "enum", members=CONTRACT_CLASSES),
    Field("contracted_acres", "number", exclusive_min=0),
    Field("base_price_per_unit_cents", "integer", exclusive_min=0),
    Field("conditioning_charge_per_unit_cents", "integer", minimum=0),
    Field("advance_total_cents", "integer", minimum=0),
]


@bp.post("/seed-ops/production-contracts")
def create_contract():
    authenticate(("ProgramAdmin",))
    data = parse_fields(json_body(), CONTRACT_FIELDS)
    get_grower(data["grower_id"])
    get_variety(data["variety_id"])
    field = get_field(data["production_field_id"])

    if calc.dec(data["contracted_acres"]) > calc.dec(field["acres"]):
        raise ApiError("ERR_CONTRACTED_ACRES_EXCEED_FIELD")

    rec = new_record(True)
    for f in CONTRACT_FIELDS:
        rec[f.name] = data[f.name]
    rec["advance_outstanding_cents"] = data["advance_total_cents"]
    rec["status"] = "DRAFT"
    rec["planted_on"] = None
    rec["inspection_round"] = 0
    rec["rogueing_rounds_used"] = 0
    rec["eligibility_variant_applied"] = None
    rec["eligibility_risk_score"] = None
    rec["provisional_clean_units_total"] = calc.round_half_up(0, 2)
    rec["certified_units_total"] = calc.round_half_up(0, 2)
    rec["requires_field_officer_review"] = False
    rec["cancel_reason"] = None
    rec["_planted_on_date"] = None
    rec["_lot_seq"] = 0
    db.production_contracts[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.post("/seed-ops/production-contracts/<production_contract_id>/offer")
def offer_contract(production_contract_id):
    authenticate(("ProgramAdmin",))
    contract = get_contract(production_contract_id)
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CONTRACT_STATE")

    field = db.production_fields[contract["production_field_id"]]
    variety = db.varieties[contract["variety_id"]]
    grower = db.growers[contract["grower_id"]]
    assessment = assess_field(field, variety, contract["season_year"],
                              contract["seed_class"])

    if assessment["applied_result"] != "ELIGIBLE":
        if assessment["blocking_error_id"] == "ERR_FIELD_HISTORY_RESTRICTED":
            raise ApiError("ERR_FIELD_HISTORY_RESTRICTED")

    if calc.dec(field["isolation_distance_m"]) < calc.dec(variety["isolation_min_m"]):
        raise ApiError("ERR_ISOLATION_DISTANCE_INSUFFICIENT")
    if assessment["applied_result"] != "ELIGIBLE":
        raise ApiError(assessment["blocking_error_id"])

    if grower["status"] == "SUSPENDED":
        raise ApiError("ERR_GROWER_SUSPENDED")

    for other in db.production_contracts.values():
        if (other["id"] != contract["id"]
                and other["production_field_id"] == contract["production_field_id"]
                and other["season_year"] == contract["season_year"]
                and other["status"] in OCCUPYING_STATUSES):
            raise ApiError("ERR_FIELD_SEASON_ALREADY_CONTRACTED")

    contract["status"] = "OFFERED"
    contract["eligibility_variant_applied"] = assessment["applied_variant"]
    contract["eligibility_risk_score"] = assessment["contamination_risk_score"]
    touch(contract)
    field["last_assessed_risk_score"] = assessment["contamination_risk_score"]
    touch(field)
    return object_response(public(contract))


@bp.post("/seed-ops/production-contracts/<production_contract_id>/sign")
def sign_contract(production_contract_id):
    user_id, _role = authenticate(("Grower",))
    data = parse_fields(json_body(), [Field("planted_on", "date")])
    contract = get_contract(production_contract_id)
    if user_id != contract["grower_id"]:
        raise ApiError("ERR_GROWER_SCOPE_VIOLATION")
    if contract["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_CONTRACT_STATE")
    if data["planted_on"] > db.today():
        raise ApiError("ERR_DATE_IN_FUTURE")

    contract["status"] = "PLANTED"
    contract["planted_on"] = data["planted_on__raw"]
    contract["_planted_on_date"] = data["planted_on"]
    touch(contract)
    return object_response(public(contract))


@bp.post("/seed-ops/production-contracts/<production_contract_id>/cancel")
def cancel_contract(production_contract_id):
    authenticate(("ProgramAdmin",))
    data = parse_fields(json_body(), [Field("cancel_reason", "string")])
    contract = get_contract(production_contract_id)
    if contract["status"] not in ("DRAFT", "OFFERED", "PLANTED", "ROGUEING_REQUIRED"):
        raise ApiError("ERR_INVALID_CONTRACT_STATE")

    contract["status"] = "CANCELLED"
    contract["cancel_reason"] = data["cancel_reason"]
    touch(contract)
    close_open_inspections(contract)
    return object_response(public(contract))


@bp.get("/seed-ops/production-contracts/<production_contract_id>")
def read_contract(production_contract_id):
    authenticate(("ProgramAdmin", "FieldOfficer", "ConditioningManager",
                  "SettlementAccountant", "Grower"))
    return object_response(public(get_contract(production_contract_id)))


@bp.get("/seed-ops/production-contracts")
def list_contracts():
    authenticate(("ProgramAdmin", "FieldOfficer", "ConditioningManager",
                  "SettlementAccountant", "Grower"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.production_contracts,
        grower_id=query_string("grower_id"),
        variety_id=query_string("variety_id"),
        production_field_id=query_string("production_field_id"),
        status=query_enum("status", CONTRACT_STATUSES),
        season_year=query_integer("season_year"),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)
