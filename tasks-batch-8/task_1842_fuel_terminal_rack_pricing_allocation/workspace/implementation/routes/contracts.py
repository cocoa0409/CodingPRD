from flask import Blueprint, request

from clock import today_str
from db import db
from errors import (
    ApiError, ERR_CONTRACT_NOT_ACTIVE, ERR_CONTRACT_NOT_DRAFT,
    ERR_CONTRACT_NOT_IN_WINDOW, ERR_VALIDATION, ERR_VOLUME_SHORTFALL,
    not_found,
)
from helpers import (
    get_body, list_query, new_entity, ser_contract, touch,
)
from middleware import require_roles
from response import success_list, success_object
from services import place_hold

bp = Blueprint("contracts", __name__)

_ROLES = ["PlatformAdmin", "ContractAdministrator", "CreditAnalyst", "BillingClerk"]


def _get_contract(contract_id):
    c = db.supply_contracts.get(contract_id)
    if c is None:
        raise not_found("SupplyContract {} does not exist".format(contract_id))
    return c


@bp.post("/rack/supply-contracts")
def create_contract():
    require_roles(["ContractAdministrator"])
    body = get_body()
    customer = db.customers.get(body.get("customer_id"))
    if customer is None:
        raise not_found("Customer {} does not exist".format(body.get("customer_id")))
    start = body.get("start_date")
    end = body.get("end_date")
    if start and end and end < start:
        raise ApiError(
            ERR_VALIDATION, 422, "end_date must not be before start_date"
        )
    c = new_entity({
        "customer_id": body.get("customer_id"),
        "start_date": start,
        "end_date": end,
        "volume_commitment_gallons": body.get("volume_commitment_gallons", 0),
        "lifted_to_date_gallons": 0,
        "pricing_tier": body.get("pricing_tier"),
        "status": "DRAFT",
    })
    db.supply_contracts[c["id"]] = c
    return success_object(ser_contract(c), 201)


@bp.get("/rack/supply-contracts/<contractId>")
def get_contract(contractId):
    require_roles(_ROLES)
    return success_object(ser_contract(_get_contract(contractId)))


@bp.get("/rack/supply-contracts")
def list_contracts():
    require_roles(_ROLES)
    page, total, limit, offset = list_query(
        db.supply_contracts.values(), request.args, ["customer_id", "status"]
    )
    return success_list([ser_contract(c) for c in page], total, limit, offset)


@bp.post("/rack/supply-contracts/<contractId>/activate")
def activate_contract(contractId):
    require_roles(["ContractAdministrator"])
    c = _get_contract(contractId)
    if c["status"] != "DRAFT":
        raise ApiError(
            ERR_CONTRACT_NOT_DRAFT, 409,
            "SupplyContract must be DRAFT to activate",
        )
    today = today_str()
    if not (c["start_date"] <= today <= c["end_date"]):
        raise ApiError(
            ERR_CONTRACT_NOT_IN_WINDOW, 422,
            "Current logical date is not within the contract window",
        )
    c["status"] = "ACTIVE"
    touch(c)
    return success_object(ser_contract(c))


@bp.post("/rack/supply-contracts/<contractId>/close")
def close_contract(contractId):
    require_roles(["ContractAdministrator"])
    c = _get_contract(contractId)
    if c["status"] != "ACTIVE":
        raise ApiError(
            ERR_CONTRACT_NOT_ACTIVE, 409,
            "SupplyContract must be ACTIVE to close",
        )
    outcome = get_body().get("outcome")
    met = c["lifted_to_date_gallons"] >= c["volume_commitment_gallons"]
    if outcome == "CLOSED" and not met:
        raise ApiError(
            ERR_VOLUME_SHORTFALL, 422,
            "lifted_to_date_gallons is below volume_commitment_gallons",
        )

    # Either close outcome expires the contract's still-ACTIVE rights.
    for r in list(db.lifting_rights.values()):
        if r["contract_id"] == c["id"] and r["status"] == "ACTIVE":
            r["status"] = "EXPIRED"
            touch(r)

    if met:
        c["status"] = "CLOSED"
    else:
        c["status"] = "DEFAULTED"
    touch(c)

    if not met:
        customer = db.customers.get(c["customer_id"])
        if customer is not None:
            place_hold(customer, "CONTRACT_DEFAULT", "CONTRACT_DEFAULT")
    return success_object(ser_contract(c))
