"""Bid contracts: the lifecycle, the ledger view and season-end reconciliation."""

from flask import Blueprint, g

import db
import response
from db import store, touch
from errors import (
    ERR_CONTRACT_INVALID_STATE,
    ERR_PRESEASON_COVERAGE_SHORT,
    ERR_PRESEASON_WINDOW_CLOSED,
    fail,
    invalid,
)
from middleware import auth, require_distinct_actor
from services import calc, derive, serialize
from util import D, body, enum, filter_str, number, q2, require, state_code, text

bp = Blueprint("contracts", __name__)

JURISDICTIONS = ("MUNICIPAL", "COUNTY", "STATE")
OUTCOMES = ("AWARD", "LOSE")


def _require_status(contract, allowed):
    if contract["status"] not in allowed:
        fail(ERR_CONTRACT_INVALID_STATE,
             "contract status %s does not admit this operation" % contract["status"])


@bp.post("/salt/bid-contracts")
@auth("ContractAdministrator")
def create_contract():
    payload = body()
    require(payload, ["season_forecast_id", "customer_name", "jurisdiction_level",
                      "state_code", "product_line", "committed_tons",
                      "guaranteed_price_per_ton", "min_take_pct", "max_take_pct",
                      "failure_to_supply_penalty_per_ton", "price_guarantee_cap_pct"])
    jurisdiction = enum(payload, "jurisdiction_level", JURISDICTIONS)
    product_line = enum(payload, "product_line", calc.PRODUCT_LINES)
    customer = text(payload, "customer_name", minlen=1, maxlen=120)
    code = state_code(payload)
    committed = number(payload, "committed_tons", gt=0)
    price = number(payload, "guaranteed_price_per_ton", gt=0)
    min_take = number(payload, "min_take_pct", minv=50, maxv=100)
    max_take = number(payload, "max_take_pct", minv=100, maxv=200)
    penalty = number(payload, "failure_to_supply_penalty_per_ton", minv=0)
    cap = number(payload, "price_guarantee_cap_pct", minv=0, maxv=50)
    if D(min_take) > D(max_take):
        invalid("min_take_pct may not exceed max_take_pct")

    forecast = derive.get_forecast(payload["season_forecast_id"])

    contract = db.stamp()
    contract.update({
        "season_forecast_id": forecast["id"],
        "customer_name": customer,
        "jurisdiction_level": jurisdiction,
        "state_code": code,
        "product_line": product_line,
        "committed_tons": committed,
        "guaranteed_price_per_ton": price,
        "min_take_pct": min_take,
        "max_take_pct": max_take,
        "failure_to_supply_penalty_per_ton": penalty,
        "price_guarantee_cap_pct": cap,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "contract_value_usd": None,
        "season_penalty_usd": None,
        "penalty_reconciliation_delta_usd": None,
    })
    store.contracts[contract["id"]] = contract
    return response.created(serialize.contract_json(contract))


@bp.get("/salt/bid-contracts/<contract_id>")
@auth()
def read_contract(contract_id):
    return response.ok(serialize.contract_json(derive.get_contract(contract_id)))


@bp.get("/salt/bid-contracts")
@auth()
def list_contracts():
    rows = list(store.contracts.values())
    for name in ("season_forecast_id", "status", "product_line", "state_code",
                 "jurisdiction_level"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return response.page(db.by_seq(rows), serialize.contract_json)


@bp.get("/salt/bid-contracts/<contract_id>/ledger")
@auth("ContractAdministrator", "ComplianceOfficer", "LogisticsPlanner")
def read_ledger(contract_id):
    contract = derive.get_contract(contract_id)
    return response.ok(serialize.ledger_json(contract))


@bp.post("/salt/bid-contracts/<contract_id>/submit")
@auth("ContractAdministrator")
def submit_contract(contract_id):
    contract = derive.get_contract(contract_id)
    _require_status(contract, ("DRAFT",))
    contract["status"] = "SUBMITTED"
    contract["submitted_by_user_id"] = g.user_id
    touch(contract)
    return response.ok(serialize.contract_json(contract))


@bp.post("/salt/bid-contracts/<contract_id>/decision")
@auth("ContractAdministrator")
def decide_contract(contract_id):
    payload = body()

    # segregation of duties: the decider may not be the submitter
    known = store.contracts.get(contract_id)
    if known is not None:
        require_distinct_actor(known.get("submitted_by_user_id"),
                               "the deciding user may not be the submitter")

    require(payload, ["outcome"])
    outcome = enum(payload, "outcome", OUTCOMES)
    contract = derive.get_contract(contract_id)
    _require_status(contract, ("SUBMITTED",))

    if outcome == "AWARD":
        contract["status"] = "AWARDED"
        contract["contract_value_usd"] = q2(
            D(contract["committed_tons"]) * D(contract["guaranteed_price_per_ton"]))
    else:
        contract["status"] = "LOST"
    contract["decided_by_user_id"] = g.user_id
    touch(contract)
    return response.ok(serialize.contract_json(contract))


@bp.post("/salt/bid-contracts/<contract_id>/activate")
@auth("ContractAdministrator")
def activate_contract(contract_id):
    contract = derive.get_contract(contract_id)
    _require_status(contract, ("AWARDED",))
    forecast = derive.get_forecast(contract["season_forecast_id"])
    if db.now() > forecast["preseason_lock_date"]:
        fail(ERR_PRESEASON_WINDOW_CLOSED,
             "the pre-season window closed at %s" % forecast["preseason_lock_date"])
    coverage = derive.contract_preseason_coverage(contract)
    required = derive.contract_preseason_required(contract)
    if D(coverage) < D(required):
        fail(ERR_PRESEASON_COVERAGE_SHORT,
             "pre-season coverage %s is below the required %s" % (coverage, required))

    contract["status"] = "ACTIVE"
    touch(contract)
    return response.ok(serialize.contract_json(contract))


@bp.post("/salt/bid-contracts/<contract_id>/close-season")
@auth("ContractAdministrator")
def close_season(contract_id):
    contract = derive.get_contract(contract_id)
    _require_status(contract, ("ACTIVE",))

    fulfilled = derive.contract_fulfilled_tons(contract["id"])
    accrued = derive.contract_penalty_accrued(contract["id"])
    season_penalty = calc.season_penalty(contract, fulfilled)
    contract["season_penalty_usd"] = season_penalty
    contract["penalty_reconciliation_delta_usd"] = q2(
        D(season_penalty) - D(accrued))
    floor = derive.contract_preseason_required(contract)
    contract["status"] = "FORFEITED" if D(fulfilled) < D(floor) else "CLOSED"
    touch(contract)
    return response.ok(serialize.contract_json(contract))
