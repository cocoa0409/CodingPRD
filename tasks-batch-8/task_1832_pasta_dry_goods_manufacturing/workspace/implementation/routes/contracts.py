"""IngredientContract + PriceIndexReading endpoints."""
from flask import Blueprint

import db
from db import new_common, new_id, new_log_entry, store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, ok, paginate
from services.cascades import sweep_all_contracts, sweep_contract
from validation import parse_body, require_path_entity

bp = Blueprint("contracts", __name__)

INGREDIENT_TYPES = ["SEMOLINA", "DURUM_SEMOLINA", "RICE_FLOUR"]
PRICING_METHODS = ["INDEX_LAGGED", "SPOT_BLEND"]


def _get_contract(contract_id):
    contract = require_path_entity(store.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    sweep_contract(contract)
    return contract


@bp.post("/ingredient-contracts")
def create_contract():
    uid, role, _ = get_context()
    require_roles(["ProcurementManager"])
    body = parse_body({
        "contract_code": ("string", True, None),
        "supplier_name": ("string", True, None),
        "ingredient_type": ("enum", True, INGREDIENT_TYPES),
        "base_price_cents_per_kg": ("integer", True, None),
        "reference_index_value": ("number", True, None),
        "pricing_method": ("enum", True, PRICING_METHODS),
        "effective_start": ("date", True, None),
        "effective_end": ("date", True, None),
    }, allow_empty=False)
    if db.dec(body["reference_index_value"]) <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "reference_index_value must be > 0")
    effective_start = db.parse_date(body["effective_start"])
    effective_end = db.parse_date(body["effective_end"])
    if effective_end <= effective_start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "effective_end must be strictly later than effective_start")
    contract = {
        "id": new_id(),
        "contract_code": body["contract_code"],
        "supplier_name": body["supplier_name"],
        "ingredient_type": body["ingredient_type"],
        "base_price_cents_per_kg": body["base_price_cents_per_kg"],
        "reference_index_value": body["reference_index_value"],
        "pricing_method": body["pricing_method"],
        "effective_start": effective_start,
        "effective_end": effective_end,
        "cumulative_delivered_kg": 0,
        "status": "DRAFT",
        "created_by_user_id": uid,
    }
    new_common(contract)
    store.contracts[contract["id"]] = contract
    return created(contract)


@bp.get("/ingredient-contracts/<contract_id>")
def get_contract(contract_id):
    get_context()
    require_roles(ALL_ROLES)
    return ok(_get_contract(contract_id))


@bp.post("/ingredient-contracts/<contract_id>/activate")
def activate_contract(contract_id):
    get_context()
    require_roles(["PlantManager"])
    contract = _get_contract(contract_id)
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT contract can be activated")
    if contract["effective_end"] < db.clock_today():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Cannot activate an already-lapsed window")
    sweep_all_contracts()
    for other in store.contracts.values():
        if (other["id"] != contract["id"] and other["status"] == "ACTIVE"
                and other["ingredient_type"] == contract["ingredient_type"]
                and contract["effective_start"] <= other["effective_end"]
                and other["effective_start"] <= contract["effective_end"]):
            raise ApiError("ERR_CONTRACT_WINDOW_OVERLAP", 409,
                           "Another ACTIVE contract of the same ingredient_type overlaps this window")
    contract["status"] = "ACTIVE"
    touch(contract)
    return ok(contract)


@bp.post("/ingredient-contracts/<contract_id>/close")
def close_contract(contract_id):
    get_context()
    require_roles(["ProcurementManager"])
    contract = _get_contract(contract_id)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACTIVE contract can be closed")
    contract["status"] = "CLOSED"
    touch(contract)
    return ok(contract)


@bp.post("/ingredient-contracts/<contract_id>/index-readings")
def create_index_reading(contract_id):
    get_context()
    require_roles(["ProcurementManager"])
    contract = _get_contract(contract_id)
    body = parse_body({
        "effective_date": ("date", True, None),
        "index_value": ("number", True, None),
    }, allow_empty=False)
    if db.dec(body["index_value"]) <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "index_value must be > 0")
    if contract["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409,
                       "Index readings attach only to DRAFT or ACTIVE contracts")
    effective_date = db.parse_date(body["effective_date"])
    for reading in store.index_readings.values():
        if (reading["contract_id"] == contract["id"]
                and reading["effective_date"] == effective_date):
            raise ApiError("ERR_DUPLICATE_INDEX_READING", 409,
                           "A reading already exists for this contract and effective_date")
    reading = {
        "id": new_id(),
        "contract_id": contract["id"],
        "effective_date": effective_date,
        "index_value": body["index_value"],
    }
    new_log_entry(reading)
    store.index_readings[reading["id"]] = reading
    return created(reading)


@bp.get("/ingredient-contracts/<contract_id>/index-readings")
def list_index_readings(contract_id):
    get_context()
    require_roles(ALL_ROLES)
    contract = _get_contract(contract_id)
    rows = [r for r in store.index_readings.values() if r["contract_id"] == contract["id"]]
    return ok(paginate(rows), rtype="array", pagination=paginate)
