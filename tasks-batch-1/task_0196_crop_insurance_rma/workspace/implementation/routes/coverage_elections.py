"""CoverageElection routes (PRD §3.3, §3.4)."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_role, get_json
from services.common import (
    make_common, public, touch, lookup,
    as_number, as_int, as_string, as_enum, parse_pagination, paginate,
)
from services import ledger
from services import calculations as calc
from services import transitions

bp = Blueprint("coverage_elections", __name__)

READ_ROLES = {"RmaAdmin", "Agent", "LossAdjuster"}


@bp.post("/coverage-elections")
def create_election():
    _, role = authenticate()
    require_role(role, {"Agent"})
    body = get_json()
    policy_id = as_string(body, "policy_id")
    commodity_program_id = as_string(body, "commodity_program_id")
    plan_type = as_enum(body, "plan_type", {"YP", "RP", "RP_HPE"})
    aph_yield = as_number(body, "aph_yield")
    coverage_level = as_number(body, "coverage_level")

    # Body well-formedness (priority 4)
    if aph_yield <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "aph_yield must be > 0")
    if calc._coverage_key(coverage_level) is None:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "coverage_level must be one of the allowed levels")

    # FK existence (priority 3, after path; body FKs)
    policy = lookup(db.policies, policy_id)
    program = lookup(db.commodity_programs, commodity_program_id)

    # Business referential (priority 10): program must be OPEN
    if program["status"] != "OPEN":
        raise errors.err(errors.ERR_PROGRAM_NOT_OPEN, "Commodity program is not OPEN")

    guarantee_bu = calc.yield_guarantee_bu(aph_yield, coverage_level)
    liability = calc.dollar_liability_per_acre_cents(guarantee_bu, program["projected_price"])
    subsidy_factor = calc.subsidy_factor_for(coverage_level)

    entity = make_common()
    entity.update({
        "policy_id": policy_id,
        "commodity_program_id": commodity_program_id,
        "plan_type": plan_type,
        "aph_yield": aph_yield,
        "coverage_level": coverage_level,
        "yield_guarantee_bu": guarantee_bu,
        "dollar_liability_per_acre_cents": liability,
        "total_premium_cents": 0,
        "subsidy_factor": subsidy_factor,
        "subsidy_cents": 0,
        "producer_premium_cents": 0,
        "status": "ELECTED",
    })
    db.coverage_elections[entity["id"]] = entity
    # total_premium_cents = 0 until units added (no units yet -> stays 0)
    return response.success_object(public(entity), 201)


@bp.get("/coverage-elections/<eid>")
def get_election(eid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    entity = lookup(db.coverage_elections, eid)
    return response.success_object(public(entity), 200)


@bp.get("/coverage-elections")
def list_elections():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.coverage_elections.values())
    if "policy_id" in request.args:
        items = [e for e in items if e["policy_id"] == request.args.get("policy_id")]
    if "commodity_program_id" in request.args:
        items = [e for e in items if e["commodity_program_id"] == request.args.get("commodity_program_id")]
    page, total = paginate(items, limit, offset)
    return response.success_array(page, limit, offset, total, 200)


@bp.get("/coverage-elections/<eid>/units")
def list_election_units(eid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    lookup(db.coverage_elections, eid)
    limit, offset = parse_pagination()
    items = ledger.units_of_election(eid)
    page, total = paginate(items, limit, offset)
    return response.success_array(page, limit, offset, total, 200)


@bp.post("/coverage-elections/<eid>/void")
def void_election_route(eid):
    _, role = authenticate()
    require_role(role, {"Agent"})
    election = lookup(db.coverage_elections, eid)
    body = get_json()
    # Body well-formedness (priority 4): expected_policy_version required
    expected = as_int(body, "expected_policy_version")
    policy = ledger.policy_of_election(election)
    if policy is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Owning policy not found")

    # OCC (priority 5) before state check (PRD §2.7, §2.9)
    if expected != policy["version"]:
        raise errors.err(errors.ERR_STALE_VERSION,
                         "expected_policy_version does not match the policy's current version")

    # State check (priority 6): void is defined from ELECTED
    if election["status"] != "ELECTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Election is not in ELECTED status")

    # Business rule: no unit has an ACCEPTED acreage report (PRD §3.3)
    for u in ledger.units_of_election(eid):
        for r in ledger.reports_of_unit(u["id"]):
            if r["status"] == "ACCEPTED":
                raise errors.err(errors.ERR_ELECTION_ALREADY_REPORTED,
                                 "A unit under this election already has an ACCEPTED acreage report")

    transitions.void_election(election, cascade=True)
    return response.success_object(public(election), 200)
