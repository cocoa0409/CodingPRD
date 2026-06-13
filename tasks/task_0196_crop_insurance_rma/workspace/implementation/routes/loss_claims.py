"""LossClaim routes (PRD §3.6, §3.7)."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_role, get_json
from services.common import (
    make_common, public, touch, lookup,
    as_number, as_string, parse_datetime, parse_pagination, paginate,
)
from services import ledger
from services import calculations as calc
from services import transitions

bp = Blueprint("loss_claims", __name__)

READ_ROLES = {"RmaAdmin", "Agent", "LossAdjuster"}


def _policy_of_claim(claim):
    unit = db.units.get(claim["unit_id"])
    if unit is None:
        return None, None, None
    election = ledger.election_of_unit(unit)
    if election is None:
        return unit, None, None
    policy = ledger.policy_of_election(election)
    return unit, election, policy


@bp.post("/loss-claims")
def create_loss_claim():
    _, role = authenticate()
    require_role(role, {"Agent"})
    body = get_json()
    unit_id = as_string(body, "unit_id")
    harvest_date = parse_datetime(body, "harvest_date", required=True)
    production_to_count_bu = as_number(body, "production_to_count_bu")
    if production_to_count_bu < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "production_to_count_bu must be >= 0")
    assigned_adjuster_id = as_string(body, "assigned_adjuster_id")

    lookup(db.units, unit_id)
    lookup(db.agents, assigned_adjuster_id)

    entity = make_common()
    entity.update({
        "unit_id": unit_id,
        "harvest_date": body["harvest_date"],
        "production_to_count_bu": production_to_count_bu,
        "assigned_adjuster_id": assigned_adjuster_id,
        "indemnity_cents": 0,
        "revision_count": 0,
        "status": "DRAFT",
    })
    db.loss_claims[entity["id"]] = entity
    return response.success_object(public(entity), 201)


@bp.get("/loss-claims/<cid>")
def get_loss_claim(cid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    entity = lookup(db.loss_claims, cid)
    return response.success_object(public(entity), 200)


@bp.get("/loss-claims")
def list_loss_claims():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.loss_claims.values())
    if "unit_id" in request.args:
        items = [c for c in items if c["unit_id"] == request.args.get("unit_id")]
    if "assigned_adjuster_id" in request.args:
        items = [c for c in items if c["assigned_adjuster_id"] == request.args.get("assigned_adjuster_id")]
    page, total = paginate(items, limit, offset)
    return response.success_array(page, limit, offset, total, 200)


@bp.post("/loss-claims/<cid>/submit")
def submit_loss_claim(cid):
    _, role = authenticate()
    require_role(role, {"Agent"})
    claim = lookup(db.loss_claims, cid)
    # State check (priority 6)
    if claim["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Loss claim is not in DRAFT status")
    unit, election, policy = _policy_of_claim(claim)
    # Unit must be REPORTED or ACTIVE
    if unit is None or unit["status"] not in ("REPORTED", "ACTIVE"):
        raise errors.err(errors.ERR_UNIT_NOT_REPORTED, "Unit is not REPORTED or ACTIVE")
    # Harvest price published for RP/RP_HPE
    if election is not None and election["plan_type"] in ("RP", "RP_HPE"):
        program = ledger.program_of_election(election)
        if not program or not program.get("harvest_price_published"):
            raise errors.err(errors.ERR_HARVEST_PRICE_UNAVAILABLE,
                             "Harvest price has not been published for this revenue plan")

    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    if unit["status"] == "REPORTED":
        unit["status"] = "ACTIVE"
        touch(unit)
    return response.success_object(public(claim), 200)


@bp.post("/loss-claims/<cid>/return")
def return_loss_claim(cid):
    user_id, role = authenticate()
    require_role(role, {"LossAdjuster"})
    claim = lookup(db.loss_claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Loss claim is not in UNDER_REVIEW status")
    # Acting adjuster must be the assigned adjuster (PRD §3.6)
    if user_id != claim["assigned_adjuster_id"]:
        raise errors.err(errors.ERR_ADJUSTER_NOT_ASSIGNED,
                         "Acting adjuster is not the assigned adjuster")
    claim["status"] = "DRAFT"
    claim["revision_count"] += 1
    touch(claim)
    return response.success_object(public(claim), 200)


@bp.post("/loss-claims/<cid>/approve")
def approve_loss_claim(cid):
    user_id, role = authenticate()
    require_role(role, {"LossAdjuster"})
    claim = lookup(db.loss_claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Loss claim is not in UNDER_REVIEW status")
    unit, election, policy = _policy_of_claim(claim)
    # assigned-adjuster check before segregation check (PRD §3.6)
    if user_id != claim["assigned_adjuster_id"]:
        raise errors.err(errors.ERR_ADJUSTER_NOT_ASSIGNED,
                         "Acting adjuster is not the assigned adjuster")
    if policy is not None and user_id == policy["agent_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES,
                         "Acting adjuster is the policy's selling agent")

    program = ledger.program_of_election(election)
    indemnity = calc.yp_or_rp_indemnity_cents(
        election["plan_type"],
        election["yield_guarantee_bu"],
        claim["production_to_count_bu"],
        unit["acres"],
        unit["share"],
        program["projected_price"],
        program["harvest_price"],
    )
    claim["indemnity_cents"] = indemnity
    claim["status"] = "APPROVED"
    touch(claim)

    # Cascade: election REPORTED -> INDEMNIFIED; add indemnity into policy; settle unit
    transitions.cascade_election_to_indemnified(election)
    if policy is not None:
        ledger.add_policy_indemnity(policy, indemnity)
    transitions.settle_unit_if_no_open_claim(unit, exclude_loss_id=claim["id"])

    return response.success_object(public(claim), 200)


@bp.post("/loss-claims/<cid>/deny")
def deny_loss_claim(cid):
    user_id, role = authenticate()
    require_role(role, {"LossAdjuster"})
    claim = lookup(db.loss_claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Loss claim is not in UNDER_REVIEW status")
    unit, election, policy = _policy_of_claim(claim)
    if user_id != claim["assigned_adjuster_id"]:
        raise errors.err(errors.ERR_ADJUSTER_NOT_ASSIGNED,
                         "Acting adjuster is not the assigned adjuster")
    if policy is not None and user_id == policy["agent_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES,
                         "Acting adjuster is the policy's selling agent")

    claim["status"] = "DENIED"
    touch(claim)  # indemnity_cents stays 0
    transitions.settle_unit_if_no_open_claim(unit, exclude_loss_id=claim["id"])
    return response.success_object(public(claim), 200)


@bp.post("/loss-claims/<cid>/pay")
def pay_loss_claim(cid):
    _, role = authenticate()
    require_role(role, {"RmaAdmin"})
    claim = lookup(db.loss_claims, cid)
    if claim["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Loss claim is not in APPROVED status")
    claim["status"] = "PAID"
    touch(claim)
    return response.success_object(public(claim), 200)
