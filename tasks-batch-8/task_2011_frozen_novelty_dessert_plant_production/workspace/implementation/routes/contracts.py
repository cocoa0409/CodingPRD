"""Co-pack contracts (PRD §3.2)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PRODUCT_DISCONTINUED,
    ERR_STALE_VERSION,
)
from middleware import authenticate, check_ownership, ALL_ROLES
from response import success_obj, success_list
from services import serialize, shortfall_penalty_cents
from util import (
    apply_filters,
    body_json,
    check_shape,
    exist_body_fks,
    paginate,
    pagination_params,
    parse_date,
    path_entity,
)

bp = Blueprint("contracts", __name__)

CONTRACT_SPEC = {
    "contract_code": {"type": "string", "required": True},
    "customer_id": {"type": "string", "required": True},
    "product_id": {"type": "string", "required": True},
    "committed_units": {"type": "integer", "min": 1, "required": True},
    "unit_price_cents": {"type": "integer", "min": 0, "required": True},
    "start_date": {"type": "date", "required": True},
    "end_date": {"type": "date", "required": True},
}

AMEND_SPEC = {
    "expected_contract_version": {"type": "integer", "required": True},
    "committed_units": {"type": "integer", "min": 1},
    "unit_price_cents": {"type": "integer", "min": 0},
    "end_date": {"type": "date"},
}


@bp.route("/co-pack-contracts", methods=["POST"])
def create_contract():
    authenticate({"PlantManager"})
    body = body_json()
    exist_body_fks(body, {
        "customer_id": ("customers", "customer"),
        "product_id": ("products", "product"),
    })
    check_shape(body, CONTRACT_SPEC)
    if parse_date(body["end_date"]) <= parse_date(body["start_date"]):
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_date must be after start_date")
    contract = db.new_entity("contracts", {
        "contract_code": body["contract_code"],
        "customer_id": body["customer_id"],
        "product_id": body["product_id"],
        "committed_units": body["committed_units"],
        "unit_price_cents": body["unit_price_cents"],
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "status": "DRAFT",
        "pinned_product_version": None,
        "delivered_units": 0,
        "shortfall_penalty_cents": None,
    })
    return success_obj(serialize("contracts", contract), 201)


@bp.route("/co-pack-contracts", methods=["GET"])
def list_contracts():
    authenticate(ALL_ROLES)
    items = apply_filters(db.all_of("contracts"), ["customer_id", "product_id", "status"])
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("contracts", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/co-pack-contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    authenticate(ALL_ROLES)
    contract = path_entity("contracts", contract_id, "contract")
    return success_obj(serialize("contracts", contract))


@bp.route("/co-pack-contracts/<contract_id>/submit", methods=["POST"])
def submit_contract(contract_id):
    user_id, _role = authenticate({"CustomerRep"})
    contract = path_entity("contracts", contract_id, "contract")
    if contract["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "contract is not DRAFT")
    check_ownership(user_id, contract["customer_id"], "contract")
    contract["status"] = "SUBMITTED"
    db.touch(contract)
    return success_obj(serialize("contracts", contract))


@bp.route("/co-pack-contracts/<contract_id>/approve", methods=["POST"])
def approve_contract(contract_id):
    authenticate({"PlantManager"})
    contract = path_entity("contracts", contract_id, "contract")
    if contract["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "contract is not SUBMITTED")
    product = db.get("products", contract["product_id"])
    if product is None or product["status"] != "ACTIVE":
        raise ApiError(
            ERR_PRODUCT_DISCONTINUED, 422, "contract product is not ACTIVE"
        )
    if not product.get("co_pack_only"):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "contract product is not co_pack_only"
        )
    contract["pinned_product_version"] = product["version"]
    contract["status"] = "APPROVED"
    db.touch(contract)
    return success_obj(serialize("contracts", contract))


@bp.route("/co-pack-contracts/<contract_id>/amend", methods=["POST"])
def amend_contract(contract_id):
    authenticate({"PlantManager"})
    contract = path_entity("contracts", contract_id, "contract")
    body = body_json()
    check_shape(body, AMEND_SPEC)
    if "end_date" in body and body["end_date"] is not None:
        if parse_date(body["end_date"]) <= parse_date(contract["start_date"]):
            raise ApiError(ERR_INVALID_REQUEST, 400, "end_date must be after start_date")
    if contract["status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError(
            ERR_INVALID_STATE, 409, "contract must be APPROVED or ACTIVE to amend"
        )
    # OCC (PRD §2.6).
    if body["expected_contract_version"] != contract["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_contract_version does not match the contract's current version",
        )
    for field in ("committed_units", "unit_price_cents", "end_date"):
        if field in body and body[field] is not None:
            contract[field] = body[field]
    db.touch(contract)
    return success_obj(serialize("contracts", contract))


@bp.route("/co-pack-contracts/<contract_id>/cancel", methods=["POST"])
def cancel_contract(contract_id):
    authenticate({"PlantManager"})
    contract = path_entity("contracts", contract_id, "contract")
    if contract["status"] not in ("DRAFT", "SUBMITTED", "APPROVED", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, 409, "contract cannot be canceled")
    if contract["status"] in ("APPROVED", "ACTIVE"):
        # Shortfall penalty when delivered < committed; 0 when fulfilled.
        contract["shortfall_penalty_cents"] = shortfall_penalty_cents(contract)
    contract["status"] = "CANCELED"
    db.touch(contract)
    return success_obj(serialize("contracts", contract))
