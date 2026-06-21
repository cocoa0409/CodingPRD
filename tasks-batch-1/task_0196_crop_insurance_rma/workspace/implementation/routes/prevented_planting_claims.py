"""PreventedPlantingClaim routes (PRD §3.8)."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_role, get_json
from services.common import (
    make_common, public, touch, lookup,
    as_number, as_string, as_enum, parse_pagination, paginate,
)
from services import ledger
from services import calculations as calc
from services import transitions

bp = Blueprint("prevented_planting_claims", __name__)

READ_ROLES = {"RmaAdmin", "Agent", "LossAdjuster"}


def _ctx(claim):
    unit = db.units.get(claim["unit_id"])
    if unit is None:
        return None, None, None
    election = ledger.election_of_unit(unit)
    if election is None:
        return unit, None, None
    policy = ledger.policy_of_election(election)
    return unit, election, policy


@bp.post("/prevented-planting-claims")
def create_pp_claim():
    _, role = authenticate()
    require_role(role, {"Agent"})
    body = get_json()
    unit_id = as_string(body, "unit_id")
    claimed_prevented_acres = as_number(body, "claimed_prevented_acres")
    if claimed_prevented_acres <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "claimed_prevented_acres must be > 0")
    cause = as_enum(body, "cause", {"EXCESS_MOISTURE", "DROUGHT", "FLOOD", "OTHER"})

    lookup(db.units, unit_id)

    entity = make_common()
    entity.update({
        "unit_id": unit_id,
        "claimed_prevented_acres": claimed_prevented_acres,
        "cause": cause,
        "pp_indemnity_cents": 0,
        "status": "DRAFT",
    })
    db.prevented_planting_claims[entity["id"]] = entity
    return response.success_object(public(entity), 201)


@bp.get("/prevented-planting-claims/<cid>")
def get_pp_claim(cid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    entity = lookup(db.prevented_planting_claims, cid)
    return response.success_object(public(entity), 200)


@bp.get("/prevented-planting-claims")
def list_pp_claims():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.prevented_planting_claims.values())
    if "unit_id" in request.args:
        items = [c for c in items if c["unit_id"] == request.args.get("unit_id")]
    page, total = paginate(items, limit, offset)
    return response.success_array(page, limit, offset, total, 200)


@bp.post("/prevented-planting-claims/<cid>/submit")
def submit_pp_claim(cid):
    _, role = authenticate()
    require_role(role, {"Agent"})
    claim = lookup(db.prevented_planting_claims, cid)
    if claim["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Claim is not in DRAFT status")
    unit, election, policy = _ctx(claim)
    # PRD §3.8 order: PP acres check, then unit-reported check
    if unit is None:
        raise errors.err(errors.ERR_UNIT_NOT_REPORTED, "Unit is not REPORTED or ACTIVE")
    if claim["claimed_prevented_acres"] > unit["prevented_acres"]:
        raise errors.err(errors.ERR_PP_ACRES_EXCEED_REPORTED,
                         "claimed_prevented_acres exceeds the unit's reported prevented_acres")
    if unit["status"] not in ("REPORTED", "ACTIVE"):
        raise errors.err(errors.ERR_UNIT_NOT_REPORTED, "Unit is not REPORTED or ACTIVE")

    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    if unit["status"] == "REPORTED":
        unit["status"] = "ACTIVE"
        touch(unit)
    return response.success_object(public(claim), 200)


@bp.post("/prevented-planting-claims/<cid>/approve")
def approve_pp_claim(cid):
    user_id, role = authenticate()
    require_role(role, {"LossAdjuster"})
    claim = lookup(db.prevented_planting_claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Claim is not in UNDER_REVIEW status")
    unit, election, policy = _ctx(claim)
    # Segregation of duties (PRD §3.8)
    if policy is not None and user_id == policy["agent_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES,
                         "Acting adjuster is the policy's selling agent")

    program = ledger.program_of_election(election)
    indemnity = calc.pp_indemnity_cents(
        election["dollar_liability_per_acre_cents"],
        program["pp_coverage_factor"],
        claim["claimed_prevented_acres"],
        unit["share"],
    )
    claim["pp_indemnity_cents"] = indemnity
    claim["status"] = "APPROVED"
    touch(claim)

    transitions.cascade_election_to_indemnified(election)
    if policy is not None:
        ledger.add_policy_indemnity(policy, indemnity)
    transitions.settle_unit_if_no_open_claim(unit, exclude_pp_id=claim["id"])

    return response.success_object(public(claim), 200)


@bp.post("/prevented-planting-claims/<cid>/deny")
def deny_pp_claim(cid):
    user_id, role = authenticate()
    require_role(role, {"LossAdjuster"})
    claim = lookup(db.prevented_planting_claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Claim is not in UNDER_REVIEW status")
    unit, election, policy = _ctx(claim)
    if policy is not None and user_id == policy["agent_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES,
                         "Acting adjuster is the policy's selling agent")

    claim["status"] = "DENIED"
    touch(claim)  # pp_indemnity_cents stays 0
    transitions.settle_unit_if_no_open_claim(unit, exclude_pp_id=claim["id"])
    return response.success_object(public(claim), 200)
