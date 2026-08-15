"""NegotiationRound endpoints."""

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_OFFER_NOT_FOUND, ERR_NEGOTIATION_ROUND_NOT_FOUND,
    ERR_INVALID_OFFER_STATE, ERR_STALE_OFFER_VERSION, ERR_NEGOTIATION_ROUND_LIMIT,
    ERR_BASE_EXCEEDS_HARD_CAP, ERR_ROUND_NOT_PENDING,
    ERR_CONCESSION_EXCEEDS_AUTHORITY, ERR_REQUISITION_BUDGET_EXCEEDED,
    ERR_OFFER_EXPIRED,
)
from middleware import (
    get_actor, require_role, get_json_body, validate_fields, req_enum, req_int,
    req_number,
)
from response import success
from services import calc
from services import offer_ops

bp = Blueprint("negotiation_rounds", __name__)

READ_ROLES = ["Recruiter", "HiringManager", "CompAnalyst", "DepartmentDirector",
              "VPPeople", "HRAdmin"]
DECIDE_ROLES = ["Recruiter", "HiringManager", "VPPeople"]
MAX_ROUNDS = 3


@bp.route("/api/offers/<offer_id>/negotiation-rounds", methods=["POST"])
def create(offer_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body,
                    ["expected_offer_version", "proposed_base_cents"],
                    ["proposed_bonus_target_pct", "proposed_equity_shares"])
    proposed_base = req_int(body, "proposed_base_cents", min_value=1)
    proposed_bonus = req_number(body, "proposed_bonus_target_pct", required=False, min_value=0)
    proposed_equity = req_int(body, "proposed_equity_shares", required=False, allow_zero=True)
    expected = req_int(body, "expected_offer_version")
    require_role(role, ["Recruiter"])
    offer = db.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Offer not found")
    if offer["status"] != "EXTENDED":
        # COUNTERED offers already have a pending round; a fresh round is only
        # recorded while EXTENDED per the Offer state machine.
        if offer["status"] == "COUNTERED":
            raise_err(ERR_INVALID_OFFER_STATE, "A negotiation round is already pending")
        raise_err(ERR_INVALID_OFFER_STATE, "Rounds may only be recorded while EXTENDED")
    # lazy expiry before mutation
    if offer_ops.check_lazy_expiry(offer):
        raise_err(ERR_OFFER_EXPIRED, "Offer has expired")
    # OCC (priority 7)
    if expected != offer["version"]:
        raise_err(ERR_STALE_OFFER_VERSION, "Stale offer version")
    # Business constraints
    if offer["round_count"] >= MAX_ROUNDS:
        raise_err(ERR_NEGOTIATION_ROUND_LIMIT, "Negotiation round limit reached")
    req = db.requisitions[offer["requisition_id"]]
    if calc.exceeds_hard_cap(proposed_base, req):
        raise_err(ERR_BASE_EXCEEDS_HARD_CAP, "proposed_base_cents exceeds salary_max_cents * 1.25")
    anchor = offer["original_submitted_base_cents"]
    pct = calc.concession_pct(proposed_base, anchor)
    offer["round_count"] = offer["round_count"] + 1
    ts = db.now_ms()
    rnd = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "offer_id": offer["id"],
        "sequence": offer["round_count"],
        "proposed_base_cents": proposed_base,
        "proposed_bonus_target_pct": proposed_bonus,
        "proposed_equity_shares": proposed_equity,
        "concession_pct": pct,
        "status": "PROPOSED",
        "decided_by_user_id": None,
        "decision_note": None,
    }
    db.negotiation_rounds[rnd["id"]] = rnd
    offer["status"] = "COUNTERED"
    calc.touch(offer)  # round creation advances Offer.version
    offer_ops.append_event(offer["id"], "COUNTER_RECORDED", uid, f"sequence={rnd['sequence']}")
    return success(rnd, status=201)


@bp.route("/api/offers/<offer_id>/negotiation-rounds", methods=["GET"])
def list_rounds(offer_id):
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    offer = db.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Offer not found")
    rounds = sorted(
        [r for r in db.negotiation_rounds.values() if r["offer_id"] == offer_id],
        key=lambda r: r["sequence"],
    )
    return success(rounds, response_type="array")


@bp.route("/api/negotiation-rounds/<round_id>/decision", methods=["POST"])
def decide(round_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["outcome"], ["note"])
    outcome = req_enum(body, "outcome", ["ACCEPTED", "REJECTED"])
    note = body.get("note")
    require_role(role, DECIDE_ROLES)
    rnd = db.negotiation_rounds.get(round_id)
    if rnd is None:
        raise_err(ERR_NEGOTIATION_ROUND_NOT_FOUND, "Negotiation round not found")
    offer = db.offers[rnd["offer_id"]]
    if offer["status"] == "COUNTERED" and offer_ops.check_lazy_expiry(offer):
        raise_err(ERR_OFFER_EXPIRED, "Offer has expired")
    if rnd["status"] != "PROPOSED":
        raise_err(ERR_ROUND_NOT_PENDING, "Negotiation round is not PROPOSED")
    req = db.requisitions[offer["requisition_id"]]
    rnd["decided_by_user_id"] = uid
    rnd["decision_note"] = note

    if outcome == "REJECTED":
        rnd["status"] = "REJECTED"
        calc.touch(rnd)
        offer["status"] = "EXTENDED"
        calc.touch_no_version(offer)
        offer_ops.append_event(offer["id"], "COUNTER_REJECTED", uid, f"sequence={rnd['sequence']}")
        return success(rnd)

    # ACCEPTED: concession authority (priority 12)
    anchor = offer["original_submitted_base_cents"]
    if rnd["proposed_base_cents"] > calc.max_allowed_base(role, anchor):
        raise_err(ERR_CONCESSION_EXCEEDS_AUTHORITY,
                  "Proposed base exceeds the actor role's concession cap")

    # Budget re-check against new terms: offer is still in the counted set, so
    # release its old commitment while assessing the new one.
    new_base = rnd["proposed_base_cents"]
    new_bonus = rnd["proposed_bonus_target_pct"] if rnd["proposed_bonus_target_pct"] is not None else offer["bonus_target_pct"]
    new_equity = rnd["proposed_equity_shares"] if rnd["proposed_equity_shares"] is not None else offer["equity_shares"]
    probe = dict(offer)
    probe["base_cents"] = new_base
    probe["bonus_target_pct"] = new_bonus
    probe["equity_shares"] = new_equity
    calc.compute_costs(probe)
    old_fully = offer["fully_loaded_annual_cost_cents"]
    if probe["fully_loaded_annual_cost_cents"] > (
        req["annual_budget_cents"] - req["committed_budget_cents"] + old_fully
    ):
        raise_err(ERR_REQUISITION_BUDGET_EXCEEDED,
                  "New terms exceed the requisition's remaining budget")

    # Re-routing: recompute chain roles from new terms; compare to last fully
    # approved chain's roles.
    probe["band"] = calc.classify_band(new_base, req)
    calc.compute_equity_metrics(probe, req)
    new_chain_roles = calc.build_approval_chain(probe)
    last_approved = _last_fully_approved_chain_roles(offer["id"])
    reroute = not set(new_chain_roles).issubset(last_approved)

    # Apply terms
    offer["base_cents"] = new_base
    offer["bonus_target_pct"] = new_bonus
    offer["equity_shares"] = new_equity
    calc.recompute_offer_analytics(offer, req)
    rnd["status"] = "ACCEPTED"
    calc.touch(rnd)
    calc.touch(offer)  # counter acceptance advances Offer.version
    # Supersede GENERATED letters
    for l in db.offer_letters.values():
        if l["offer_id"] == offer["id"] and l["status"] == "GENERATED":
            l["status"] = "SUPERSEDED"
            calc.touch(l)
            offer_ops.append_event(offer["id"], "LETTER_SUPERSEDED", uid, f"sequence={l['sequence']}")
    calc.recompute_committed_budget(req)
    offer_ops.append_event(offer["id"], "COUNTER_ACCEPTED", uid, f"sequence={rnd['sequence']}")
    if reroute:
        offer["status"] = "PENDING_APPROVAL"
        calc.touch_no_version(offer)
        chain = calc.build_approval_chain(offer)
        from routes.offers import _create_steps
        _create_steps(offer, chain, uid)
    else:
        offer["status"] = "APPROVED"
        calc.touch_no_version(offer)
        for p in db.perks.values():
            if p["offer_id"] == offer["id"] and p["status"] == "LOCKED":
                p["status"] = "APPROVED"
                calc.touch(p)
        offer_ops.append_event(offer["id"], "APPROVED", uid, None)
    return success(rnd)


def _last_fully_approved_chain_roles(offer_id):
    """Roles of the last fully-approved chain. Falls back to the current chain's
    roles when nothing was approved yet (defensive; normally a chain exists)."""
    chains = {}
    for s in db.approval_steps.values():
        if s["offer_id"] == offer_id:
            chains.setdefault(s["sequence"], []).append(s)
    # Group steps into chains by creation-time clustering: a new chain starts
    # whenever sequence resets to 0.
    chain_list = []
    current = []
    for s in sorted(
        [s for s in db.approval_steps.values() if s["offer_id"] == offer_id],
        key=lambda s: (s["created_at"], s["sequence"]),
    ):
        if s["sequence"] == 0 and current:
            chain_list.append(current)
            current = []
        current.append(s)
    if current:
        chain_list.append(current)
    for chain in reversed(chain_list):
        if all(s["status"] == "APPROVED" for s in chain) and chain:
            return {s["required_role"] for s in chain}
    # No fully approved chain found; treat as empty set so any new role reroutes.
    return set()
