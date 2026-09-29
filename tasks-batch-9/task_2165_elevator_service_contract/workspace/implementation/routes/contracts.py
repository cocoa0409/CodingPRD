from flask import Blueprint

import common
from common import (
    API_PREFIX, db, new_entity, touch, serialize, object_response, paginate,
    sorted_rows, filter_equals, authenticate, json_body, get_contract, fail,
    req_string, req_enum, req_int, req_date, num,
    ALL_ROLES, ROLE_ADMIN, SCOPE_TYPES, PENALTY_SCHEDULES,
)
from cascades import terminate_contract

bp = Blueprint("contracts", __name__)


def contract_json(contract):
    data = serialize(contract)
    return data


@bp.route(API_PREFIX + "/contracts", methods=["POST"])
def create_contract():
    authenticate([ROLE_ADMIN])
    body = json_body()

    building_name = req_string(body, "building_name")
    building_address = req_string(body, "building_address")
    jurisdiction_code = req_string(body, "jurisdiction_code")
    fire_district_code = req_string(body, "fire_district_code")
    building_manager_user_id = req_string(body, "building_manager_user_id")
    contractor_user_id = req_string(body, "contractor_user_id")
    scope_type = req_enum(body, "scope_type", SCOPE_TYPES)
    penalty_schedule = req_enum(body, "penalty_schedule", PENALTY_SCHEDULES)
    monthly_base_fee_cents = req_int(body, "monthly_base_fee_cents", 1)
    callback_response_minutes = req_int(body, "callback_response_minutes", 1)
    entrapment_response_minutes = req_int(body, "entrapment_response_minutes", 1)
    term_start = req_date(body, "term_start_date")
    term_end = req_date(body, "term_end_date")
    if term_end <= term_start:
        fail("ERR_VALIDATION", "term_end_date must be strictly after term_start_date.")

    contract = new_entity({
        "building_name": building_name,
        "building_address": building_address,
        "jurisdiction_code": jurisdiction_code,
        "fire_district_code": fire_district_code,
        "building_manager_user_id": building_manager_user_id,
        "contractor_user_id": contractor_user_id,
        "scope_type": scope_type,
        "penalty_schedule": penalty_schedule,
        "monthly_base_fee_cents": monthly_base_fee_cents,
        "callback_response_minutes": callback_response_minutes,
        "entrapment_response_minutes": entrapment_response_minutes,
        "term_start_date": body["term_start_date"],
        "term_end_date": body["term_end_date"],
        "status": "DRAFT",
        "cars_out_of_service_count": 0,
        "penalty_lifetime_assessed_cents": 0,
        "penalty_lifetime_waived_cents": 0,
        "penalty_lifetime_credited_cents": 0,
        "penalty_balance_cents": 0,
        "performance_score": None,
        "renegotiation_round_count": 0,
    })
    db.contracts[contract["id"]] = contract
    return object_response(contract_json(contract), 201)


@bp.route(API_PREFIX + "/contracts/<contract_id>", methods=["GET"])
def read_contract(contract_id):
    authenticate(ALL_ROLES)
    contract = get_contract(contract_id)
    return object_response(contract_json(contract))


@bp.route(API_PREFIX + "/contracts", methods=["GET"])
def list_contracts():
    authenticate([ROLE_ADMIN])
    rows = sorted_rows(db.contracts)
    rows = filter_equals(rows, "status")
    rows = filter_equals(rows, "scope_type")
    return paginate(rows)


@bp.route(API_PREFIX + "/contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    authenticate([ROLE_ADMIN])
    contract = get_contract(contract_id)
    if contract["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION")
    if contract["term_end_date"] <= contract["term_start_date"]:
        fail("ERR_VALIDATION", "term_end_date must be strictly after term_start_date.")
    contract["status"] = "ACTIVE"
    touch(contract)
    return object_response(contract_json(contract))


@bp.route(API_PREFIX + "/contracts/<contract_id>/terminate", methods=["POST"])
def terminate(contract_id):
    authenticate([ROLE_ADMIN])
    contract = get_contract(contract_id)
    if contract["status"] not in ("ACTIVE", "SERVICE_ALERT", "UNDER_RENEGOTIATION"):
        fail("ERR_INVALID_STATE_TRANSITION")
    terminate_contract(contract)
    return object_response(contract_json(contract))
