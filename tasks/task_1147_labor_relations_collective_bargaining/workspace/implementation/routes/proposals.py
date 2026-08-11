"""Proposal endpoints: drafting, side-gated transitions, counters, voids."""

from flask import Blueprint, request

import calc
import clock
from db import db
from errors import (
    ERR_AGREEMENT_NOT_BARGAINABLE,
    ERR_COSTING_NOT_LOCKED,
    ERR_ENVELOPE_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MAX_ROUNDS_EXCEEDED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_UNION_DECERTIFIED,
    ERR_UNION_MISMATCH,
    ERR_UNION_TRUSTEED,
    ERR_WRONG_SIDE,
    raise_err,
)
from helpers import (
    ALL_ROLES, authenticate, get_body, lookup, new_entity, opt_bool, opt_int,
    opt_number, opt_string, optional_body, page, parse_pagination, req_enum,
    req_string, serialize, sort_items, touch, recompute_envelope,
)
from response import success_list, success_object

bp = Blueprint("proposals", __name__)

PROPOSAL_STATUSES = (
    "DRAFT", "TENDERED", "ON_TABLE", "COUNTERED", "ACCEPTED",
    "REJECTED", "WITHDRAWN", "IMPLEMENTED", "VOID",
)

# role -> bargaining side
def _side_of(role):
    if role in ("Negotiator", "ChiefNegotiator"):
        return "EMPLOYER"
    return "UNION"  # UnionRepresentative


def _check_union_rep(user_id, agreement):
    if user_id != agreement["union_id"]:
        raise_err(ERR_UNION_MISMATCH, "X-User-ID does not match the agreement's union_id")


def _gate_actor(proposal, agreement, user_id, role, action):
    """Side / role / ownership gating for proposal actions (priority 3).

    action: one of TENDERED, ON_TABLE (table/accept/reject), WITHDRAWN, COUNTER.
    """
    if role == "UnionRepresentative":
        _check_union_rep(user_id, agreement)
    actor_side = _side_of(role)
    side = proposal["side"]
    if action in ("TENDERED", "WITHDRAWN"):
        # proposing side
        if actor_side != side:
            raise_err(ERR_WRONG_SIDE, "%s must be performed by the proposing side" % action)
        designated = "ChiefNegotiator" if side == "EMPLOYER" else "UnionRepresentative"
    else:
        # receiving side (table / accept / reject / counter)
        if actor_side == side:
            raise_err(ERR_WRONG_SIDE, "%s must be performed by the receiving side" % action)
        designated = "UnionRepresentative" if side == "EMPLOYER" else "ChiefNegotiator"
    if role != designated:
        raise_err(ERR_UNAUTHORIZED_ROLE, "Role %s may not perform %s on a %s proposal" % (role, action, side))


@bp.post("/labor-relations/proposals")
def create_proposal():
    user_id, role = authenticate(["Negotiator", "UnionRepresentative"])
    body = get_body()
    agreement_id = req_string(body, "agreement_id")
    side = req_enum(body, "side", ("EMPLOYER", "UNION"))
    title = req_string(body, "title")
    proposal_type = req_enum(body, "proposal_type", ("ECONOMIC", "NON_ECONOMIC"))
    clause_id = opt_string(body, "clause_id")
    wage_increase_pct = opt_number(body, "wage_increase_pct")
    if wage_increase_pct is not None and not (0 <= wage_increase_pct <= 0.25):
        raise_err(ERR_INVALID_REQUEST, "wage_increase_pct must be within [0, 0.25]")
    affected_headcount = opt_int(body, "affected_headcount", None)
    includes_benefits = opt_bool(body, "includes_benefits", False)
    one_time_cost_cents = opt_int(body, "one_time_cost_cents", 0)
    recurring_annual_cost_cents = opt_int(body, "recurring_annual_cost_cents", 0)

    # Resolution, left-to-right: agreement, then clause
    agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")
    if clause_id is not None:
        lookup(db.clauses, clause_id, "Clause")

    # Ownership / side gating for drafting
    if role == "UnionRepresentative":
        _check_union_rep(user_id, agreement)
        if side != "UNION":
            raise_err(ERR_WRONG_SIDE, "UnionRepresentative may only draft UNION proposals")
    else:  # Negotiator
        if side != "EMPLOYER":
            raise_err(ERR_WRONG_SIDE, "Negotiator may only draft EMPLOYER proposals")

    # Child creation gate on terminal agreements (priority 6)
    if agreement["status"] in ("ARCHIVED", "REPLACED"):
        raise_err(ERR_INVALID_STATE, "Cannot draft a proposal on a %s agreement" % agreement["status"])

    # Union standing (priority 8): DECERTIFIED blocks drafting
    union = lookup(db.unions, agreement["union_id"], "Union")
    if union["status"] == "DECERTIFIED":
        raise_err(ERR_UNION_DECERTIFIED, "Union is DECERTIFIED; drafting proposals is blocked")

    proposal = new_entity()
    proposal.update({
        "agreement_id": agreement_id,
        "clause_id": clause_id,
        "side": side,
        "title": title,
        "proposal_type": proposal_type,
        "wage_increase_pct": wage_increase_pct,
        "affected_headcount": affected_headcount,
        "includes_benefits": includes_benefits,
        "one_time_cost_cents": one_time_cost_cents,
        "recurring_annual_cost_cents": recurring_annual_cost_cents,
        "session_id": None,
        "round_number": 1,
        "status": "DRAFT",
        "submitted_by_user_id": user_id,
        "supersedes_proposal_id": None,
        "estimated_year1_cost_cents": None,
        "rejection_reason": None,
    })
    db.proposals[proposal["id"]] = proposal
    return success_object(serialize(proposal), status=201)


@bp.get("/labor-relations/proposals")
def list_proposals():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    agreement_id = request.args.get("agreement_id")
    clause_id = request.args.get("clause_id")
    supersedes = request.args.get("supersedes_proposal_id")
    side = request.args.get("side")
    status = request.args.get("status")
    items = list(db.proposals.values())
    if agreement_id is not None:
        items = [p for p in items if p["agreement_id"] == agreement_id]
    if clause_id is not None:
        items = [p for p in items if p["clause_id"] == clause_id]
    if supersedes is not None:
        items = [p for p in items if p["supersedes_proposal_id"] == supersedes]
    if side is not None:
        items = [p for p in items if p["side"] == side]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_items(items)
    slice_, total = page(items, limit, offset)
    return success_list([serialize(p) for p in slice_], limit, offset, total)


@bp.get("/labor-relations/proposals/<proposal_id>")
def get_proposal(proposal_id):
    authenticate(ALL_ROLES)
    proposal = lookup(db.proposals, proposal_id, "Proposal")
    return success_object(serialize(proposal))


@bp.post("/labor-relations/proposals/<proposal_id>/state")
def transition_proposal(proposal_id):
    user_id, role = authenticate(["Negotiator", "ChiefNegotiator", "UnionRepresentative"])
    proposal = lookup(db.proposals, proposal_id, "Proposal")
    body = get_body()
    to_status = req_string(body, "to_status")
    if to_status not in PROPOSAL_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "Unknown proposal status: %s" % to_status)
    if to_status in ("DRAFT", "COUNTERED", "IMPLEMENTED", "VOID"):
        raise_err(ERR_INVALID_STATE, "Cannot transition a proposal to %s via this endpoint" % to_status)

    agreement = lookup(db.agreements, proposal["agreement_id"], "CollectiveAgreement")
    gate_action = "ON_TABLE" if to_status in ("ON_TABLE", "ACCEPTED", "REJECTED") else to_status
    _gate_actor(proposal, agreement, user_id, role, gate_action)

    if to_status == "TENDERED":
        session_id = opt_string(body, "session_id")
        session = None
        if session_id is not None:
            session = lookup(db.sessions, session_id, "BargainingSession")
        if proposal["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Only a DRAFT proposal can be tendered")
        if not calc.is_bargainable(agreement, clock.now()):
            raise_err(ERR_AGREEMENT_NOT_BARGAINABLE, "Agreement is not bargainable")
        if session is not None:
            if session["agreement_id"] != proposal["agreement_id"] or session["status"] not in ("IN_SESSION", "COMPLETED"):
                raise_err(ERR_INVALID_STATE, "session_id must reference an IN_SESSION or COMPLETED session of the same agreement")
        union = lookup(db.unions, agreement["union_id"], "Union")
        if union["status"] == "TRUSTEED":
            raise_err(ERR_UNION_TRUSTEED, "Union is TRUSTEED; tendering is blocked")
        if union["status"] == "DECERTIFIED":
            raise_err(ERR_UNION_DECERTIFIED, "Union is DECERTIFIED; tendering is blocked")
        if session_id is not None:
            proposal["session_id"] = session_id
        proposal["status"] = "TENDERED"
        touch(proposal)

    elif to_status == "ON_TABLE":
        if proposal["status"] != "TENDERED":
            raise_err(ERR_INVALID_STATE, "Only a TENDERED proposal can be tabled")
        proposal["status"] = "ON_TABLE"
        touch(proposal)

    elif to_status == "ACCEPTED":
        if proposal["status"] != "ON_TABLE":
            raise_err(ERR_INVALID_STATE, "Only an ON_TABLE proposal can be accepted")
        if proposal["proposal_type"] == "ECONOMIC":
            locked = [s for s in db.scenarios.values()
                      if s["agreement_id"] == agreement["id"] and s["status"] == "LOCKED"
                      and proposal["id"] in s["proposal_ids"]]
            if not locked:
                raise_err(ERR_COSTING_NOT_LOCKED, "No LOCKED costing scenario covers this proposal")
            estimated = proposal["estimated_year1_cost_cents"] or 0
            if agreement["envelope_committed_cents"] + estimated > agreement["costing_envelope_cents"]:
                raise_err(ERR_ENVELOPE_EXCEEDED, "Accept would exceed the costing envelope")
        proposal["status"] = "ACCEPTED"
        touch(proposal)
        recompute_envelope(agreement)
        touch(agreement)

    elif to_status == "REJECTED":
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise_err(ERR_INVALID_REQUEST, "reason is required for REJECTED")
        if proposal["status"] != "ON_TABLE":
            raise_err(ERR_INVALID_STATE, "Only an ON_TABLE proposal can be rejected")
        proposal["rejection_reason"] = reason
        proposal["status"] = "REJECTED"
        touch(proposal)

    elif to_status == "WITHDRAWN":
        if proposal["status"] != "ON_TABLE":
            raise_err(ERR_INVALID_STATE, "Only an ON_TABLE proposal can be withdrawn")
        proposal["status"] = "WITHDRAWN"
        touch(proposal)

    return success_object(serialize(proposal))


@bp.post("/labor-relations/proposals/<proposal_id>/counter")
def counter_proposal(proposal_id):
    user_id, role = authenticate(["ChiefNegotiator", "UnionRepresentative"])
    proposal = lookup(db.proposals, proposal_id, "Proposal")
    agreement = lookup(db.agreements, proposal["agreement_id"], "CollectiveAgreement")

    # Side gating (priority 3): the receiving side counters
    _gate_actor(proposal, agreement, user_id, role, "COUNTER")

    body = get_body()
    title = req_string(body, "title")
    wage_increase_pct = opt_number(body, "wage_increase_pct")
    if wage_increase_pct is not None and not (0 <= wage_increase_pct <= 0.25):
        raise_err(ERR_INVALID_REQUEST, "wage_increase_pct must be within [0, 0.25]")
    affected_headcount = opt_int(body, "affected_headcount", None)
    includes_benefits = opt_bool(body, "includes_benefits", False)
    one_time_cost_cents = opt_int(body, "one_time_cost_cents", 0)
    recurring_annual_cost_cents = opt_int(body, "recurring_annual_cost_cents", 0)

    if proposal["status"] != "ON_TABLE":
        raise_err(ERR_INVALID_STATE, "Only an ON_TABLE proposal can be countered")
    if proposal["round_number"] >= calc.MAX_ROUNDS:
        raise_err(ERR_MAX_ROUNDS_EXCEEDED, "Proposal is already at round %d" % calc.MAX_ROUNDS)

    new_proposal = new_entity()
    new_proposal.update({
        "agreement_id": proposal["agreement_id"],
        "clause_id": proposal["clause_id"],
        "side": "UNION" if proposal["side"] == "EMPLOYER" else "EMPLOYER",
        "title": title,
        "proposal_type": proposal["proposal_type"],
        "wage_increase_pct": wage_increase_pct,
        "affected_headcount": affected_headcount,
        "includes_benefits": includes_benefits,
        "one_time_cost_cents": one_time_cost_cents,
        "recurring_annual_cost_cents": recurring_annual_cost_cents,
        "session_id": None,
        "round_number": proposal["round_number"] + 1,
        "status": "ON_TABLE",
        "submitted_by_user_id": user_id,
        "supersedes_proposal_id": proposal["id"],
        "estimated_year1_cost_cents": None,
        "rejection_reason": None,
    })
    db.proposals[new_proposal["id"]] = new_proposal

    proposal["status"] = "COUNTERED"
    touch(proposal)
    return success_object(serialize(new_proposal), status=201)


@bp.post("/labor-relations/proposals/<proposal_id>/void-implementation")
def void_implementation(proposal_id):
    authenticate(["LRAdmin"])
    proposal = lookup(db.proposals, proposal_id, "Proposal")
    optional_body()
    if proposal["status"] != "IMPLEMENTED":
        raise_err(ERR_INVALID_STATE, "Only an IMPLEMENTED proposal can be voided")
    proposal["status"] = "VOID"
    touch(proposal)
    agreement = lookup(db.agreements, proposal["agreement_id"], "CollectiveAgreement")
    recompute_envelope(agreement)
    touch(agreement)
    return success_object(serialize(proposal))
