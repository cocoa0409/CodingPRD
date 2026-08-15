"""Private-label contracts and tiered pricing (PRD 3.8)."""
from flask import Blueprint, request

import store
from auth import ALL_ROLES, authenticate, authorize
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RECIPE_NOT_ACTIVE,
    raise_err,
)
from services import (
    CONTRACT_TERMINAL_STATES,
    compute_contract_unit_price_cents,
    contract_out,
)
from util import (
    body_json, bump, get_or_404, list_response, new_record, req_int,
    req_str, success_object,
)

bp = Blueprint("contracts", __name__)


def _contract_or_404(cid):
    return get_or_404(store.contracts, cid, "PrivateLabelContract")


@bp.route("/tea-ops/contracts", methods=["POST"])
def create_contract():
    _, role = authenticate()
    authorize(role, ["AccountManager"])
    body = body_json()
    # Priority 3: body FK resolution.
    recipe_id = body.get("recipe_id")
    recipe = None
    if recipe_id is not None:
        recipe = get_or_404(store.recipes, recipe_id, "BlendRecipe")
    # Priority 13: field shape.
    customer_name = req_str(body, "customer_name")
    if not isinstance(recipe_id, str) or not recipe_id:
        raise_err(ERR_INVALID_REQUEST, "recipe_id is required and must be a string")
    minimum_units_per_run = req_int(body, "minimum_units_per_run")
    if minimum_units_per_run < 1:
        raise_err(ERR_INVALID_REQUEST, "minimum_units_per_run must be >= 1")
    contracted_total_units = req_int(body, "contracted_total_units")
    if contracted_total_units < minimum_units_per_run:
        raise_err(
            ERR_INVALID_REQUEST,
            "contracted_total_units must be >= minimum_units_per_run",
        )
    base_unit_price_cents = req_int(body, "base_unit_price_cents")
    if base_unit_price_cents < 1:
        raise_err(ERR_INVALID_REQUEST, "base_unit_price_cents must be >= 1")

    rec = new_record()
    rec.update({
        "customer_name": customer_name,
        "recipe_id": recipe["id"],
        "minimum_units_per_run": minimum_units_per_run,
        "contracted_total_units": contracted_total_units,
        "base_unit_price_cents": base_unit_price_cents,
        "contract_unit_price_cents": None,
        "fulfilled_units": 0,
        "status": "DRAFT",
    })
    store.contracts[rec["id"]] = rec
    return success_object(contract_out(rec), 201)


@bp.route("/tea-ops/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(contract_out(_contract_or_404(cid)))


@bp.route("/tea-ops/contracts", methods=["GET"])
def list_contracts():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.contracts.values())
    recipe_id = request.args.get("recipe_id")
    status = request.args.get("status")
    if recipe_id is not None:
        records = [r for r in records if r["recipe_id"] == recipe_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, contract_out)


@bp.route("/tea-ops/contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    _, role = authenticate()
    authorize(role, ["AccountManager"])
    contract = _contract_or_404(cid)
    if contract["status"] in CONTRACT_TERMINAL_STATES:
        raise_err(
            ERR_ALREADY_TERMINAL,
            "Contract is in terminal state %s" % contract["status"],
        )
    if contract["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT contract can be activated")
    recipe = store.recipes.get(contract["recipe_id"])
    if recipe is None or recipe["status"] != "ACTIVE":
        raise_err(ERR_RECIPE_NOT_ACTIVE, "Referenced recipe is not ACTIVE")
    contract["contract_unit_price_cents"] = compute_contract_unit_price_cents(
        contract["base_unit_price_cents"],
        contract["contracted_total_units"],
        recipe["certification_target"],
    )
    contract["status"] = "ACTIVE"
    bump(contract)
    return success_object(contract_out(contract))


@bp.route("/tea-ops/contracts/<cid>/cancel", methods=["POST"])
def cancel_contract(cid):
    _, role = authenticate()
    authorize(role, ["AccountManager"])
    contract = _contract_or_404(cid)
    if contract["status"] in CONTRACT_TERMINAL_STATES:
        raise_err(
            ERR_ALREADY_TERMINAL,
            "Contract is in terminal state %s" % contract["status"],
        )
    if contract["status"] not in ("DRAFT", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, "Contract cannot be cancelled")
    contract["status"] = "CANCELLED"
    bump(contract)
    return success_object(contract_out(contract))
