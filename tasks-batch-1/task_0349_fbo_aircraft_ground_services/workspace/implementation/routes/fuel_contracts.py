"""FuelContract endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from helpers import (get_json, require_string, require_int, require_enum,
                     pagination_params, paginate)

bp = Blueprint("fuel_contracts", __name__)


def contract_view(c):
    return {
        "id": c["id"],
        "operator_id": c["operator_id"],
        "product": c["product"],
        "base_price_cents_per_gal": c["base_price_cents_per_gal"],
        "tankering_fee_cents_per_gal": c["tankering_fee_cents_per_gal"],
        "contract_status": c["contract_status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/fuel-contracts", methods=["POST"])
def create_contract():
    _, role = authenticate()
    require_role(role, {"BillingClerk", "LineManager"})
    body = get_json()
    operator_id = require_string(body, "operator_id")
    product = require_enum(body, "product", {"JET_A", "AVGAS"})
    base_price = require_int(body, "base_price_cents_per_gal", minimum=1)
    tankering_fee = require_int(body, "tankering_fee_cents_per_gal", minimum=0)

    operator = db.operators.get(operator_id)
    if operator is None:
        raise err(errors.ERR_NOT_FOUND, "Operator not found.")

    c = db.common_create()
    c.update({
        "operator_id": operator_id,
        "product": product,
        "base_price_cents_per_gal": base_price,
        "tankering_fee_cents_per_gal": tankering_fee,
        "contract_status": "ACTIVE",
    })
    db.fuel_contracts[c["id"]] = c
    return success(contract_view(c), 201)


@bp.route("/fuel-contracts/<id>", methods=["GET"])
def get_contract(id):
    user_id, role = authenticate()
    require_role(role, {"FuelTech", "BillingClerk", "LineManager", "Operator"})
    c = db.fuel_contracts.get(id)
    if c is None:
        raise err(errors.ERR_NOT_FOUND, "Fuel contract not found.")
    if role == "Operator" and user_id != c["operator_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may read only its own contracts.")
    return success(contract_view(c), 200)


@bp.route("/fuel-contracts", methods=["GET"])
def list_contracts():
    user_id, role = authenticate()
    require_role(role, {"FuelTech", "BillingClerk", "LineManager", "Operator"})
    limit, offset = pagination_params()
    operator_id = request.args.get("operator_id")
    records = list(db.fuel_contracts.values())
    if role == "Operator":
        records = [r for r in records if r["operator_id"] == user_id]
    if operator_id is not None:
        records = [r for r in records if r["operator_id"] == operator_id]
    window, total = paginate(records, limit, offset)
    return list_response([contract_view(r) for r in window], limit, offset, total)


@bp.route("/fuel-contracts/<id>/expire", methods=["POST"])
def expire_contract(id):
    _, role = authenticate()
    require_role(role, {"BillingClerk", "LineManager"})
    c = db.fuel_contracts.get(id)
    if c is None:
        raise err(errors.ERR_NOT_FOUND, "Fuel contract not found.")
    c["contract_status"] = "EXPIRED"
    db.touch(c)
    return success(contract_view(c), 200)
