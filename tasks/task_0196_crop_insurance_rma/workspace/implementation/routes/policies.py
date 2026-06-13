"""Policy routes (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_role, get_json
from services.common import (
    make_common, public, touch, lookup,
    as_int, as_string, parse_pagination, paginate,
)
from services import ledger
from services import calculations as calc
from services import transitions

bp = Blueprint("policies", __name__)

READ_ROLES = {"RmaAdmin", "Agent", "LossAdjuster"}


@bp.post("/policies")
def create_policy():
    _, role = authenticate()
    require_role(role, {"Agent"})
    body = get_json()
    producer_id = as_string(body, "producer_id")
    agent_id = as_string(body, "agent_id")
    crop_year = as_int(body, "crop_year")
    # FK existence (PRD §2.8)
    lookup(db.producers, producer_id)
    lookup(db.agents, agent_id)

    entity = make_common()
    entity.update({
        "producer_id": producer_id,
        "agent_id": agent_id,
        "crop_year": crop_year,
        "total_premium_cents": 0,
        "producer_premium_cents": 0,
        "subsidy_cents": 0,
        "total_indemnity_cents": 0,
        "total_insured_acres": 0,
        "status": "DRAFT",
    })
    db.policies[entity["id"]] = entity
    return response.success_object(public(entity), 201)


@bp.get("/policies/<pid>")
def get_policy(pid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    entity = lookup(db.policies, pid)
    return response.success_object(public(entity), 200)


@bp.get("/policies")
def list_policies():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.policies.values())
    if "producer_id" in request.args:
        items = [e for e in items if e["producer_id"] == request.args.get("producer_id")]
    if "agent_id" in request.args:
        items = [e for e in items if e["agent_id"] == request.args.get("agent_id")]
    page, total = paginate(items, limit, offset)
    return response.success_array(page, limit, offset, total, 200)


@bp.get("/policies/<pid>/coverage-elections")
def list_policy_elections(pid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    lookup(db.policies, pid)
    limit, offset = parse_pagination()
    items = [e for e in db.coverage_elections.values() if e["policy_id"] == pid]
    page, total = paginate(items, limit, offset)
    return response.success_array(page, limit, offset, total, 200)


@bp.post("/policies/<pid>/activate")
def activate_policy(pid):
    _, role = authenticate()
    require_role(role, {"Agent"})
    policy = lookup(db.policies, pid)
    # State check (priority 6) before business precondition (PRD §2.9)
    if policy["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Policy is not in DRAFT status")
    elected = [e for e in ledger.elections_of_policy(pid) if e["status"] == "ELECTED"]
    if not elected:
        raise errors.err(errors.ERR_POLICY_HAS_NO_ELECTIONS,
                         "Policy has no ELECTED coverage elections")

    # Earn commissions: for each ELECTED election create/finalize AgentCommission
    for e in elected:
        rate, cents = calc.commission_cents(e["total_premium_cents"])
        existing = ledger.commissions_of_election(e["id"])
        comm = None
        for c in existing:
            if c["status"] == "EARNED":
                comm = c
                break
        if comm is None:
            comm = make_common()
            comm.update({
                "agent_id": policy["agent_id"],
                "coverage_election_id": e["id"],
                "commission_rate": rate,
                "commission_cents": cents,
                "clawback_cents": 0,
                "status": "EARNED",
            })
            db.agent_commissions[comm["id"]] = comm
        else:
            comm["commission_rate"] = rate
            comm["commission_cents"] = cents
            touch(comm)

    policy["status"] = "ACTIVE"
    touch(policy)
    return response.success_object(public(policy), 200)


@bp.post("/policies/<pid>/cancel")
def cancel_policy(pid):
    _, role = authenticate()
    require_role(role, {"Agent"})
    policy = lookup(db.policies, pid)
    if policy["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Policy is not in ACTIVE status")
    # Precondition: no open claims under this policy (PRD §3.2)
    for e in ledger.elections_of_policy(pid):
        for u in ledger.units_of_election(e["id"]):
            for c in ledger.loss_claims_of_unit(u["id"]):
                if c["status"] in ("UNDER_REVIEW", "APPROVED"):
                    raise errors.err(errors.ERR_POLICY_HAS_OPEN_CLAIMS,
                                     "Policy has loss claims in UNDER_REVIEW or APPROVED")
            for c in ledger.pp_claims_of_unit(u["id"]):
                if c["status"] in ("UNDER_REVIEW", "APPROVED"):
                    raise errors.err(errors.ERR_POLICY_HAS_OPEN_CLAIMS,
                                     "Policy has prevented-planting claims in UNDER_REVIEW or APPROVED")

    # Two-hop cascade: non-VOID elections -> VOID -> units VOID + commission clawback
    for e in ledger.elections_of_policy(pid):
        if e["status"] != "VOID":
            transitions.void_election(e, cascade=False)

    # Recompute policy ledger once, then single version bump for the cancel.
    ledger.recompute_policy_premium(policy, bump=False)
    ledger.recompute_policy_insured_acres(policy, bump=False)
    policy["status"] = "CANCELLED"
    touch(policy)
    return response.success_object(public(policy), 200)
