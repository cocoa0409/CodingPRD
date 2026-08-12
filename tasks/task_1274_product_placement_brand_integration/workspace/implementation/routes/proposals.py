"""IntegrationProposal endpoints."""
from decimal import Decimal

from flask import Blueprint

import db
import errors
import middleware
import response
import util
from services import calc, cascade
from routes.contracts import contract_view

bp = Blueprint("proposals", __name__)

DECISIONS = ["APPROVE", "REQUEST_REVISION", "REJECT"]


def proposal_view(p):
    return {k: p[k] for k in ("id", "brief_id", "opportunity_id", "proposed_fee_cents",
                              "guaranteed_seconds", "guaranteed_verbal_mentions",
                              "cross_promo_owed_count", "rate_cents_per_second",
                              "terms_revision", "status",
                              "created_at", "updated_at", "version")}


def _fee_floor_check(fee, guaranteed_seconds, rate):
    if Decimal(str(fee)) < Decimal(str(guaranteed_seconds)) * Decimal(str(rate)):
        raise errors.ApiError(errors.ERR_FEE_BELOW_MINIMUM, 400,
                              "Fee below guaranteed_seconds * rate_cents_per_second floor")


def _budget_ceiling_check(fee, brief, add_back=0):
    if fee > brief["remaining_budget_cents"] + add_back:
        raise errors.ApiError(errors.ERR_BUDGET_EXCEEDED, 422,
                              "Fee exceeds the brief's remaining budget")


def _validate_terms(body):
    fee = util.req_int(body, "proposed_fee_cents", minimum=0)
    gsec = util.req_int(body, "guaranteed_seconds", minimum=1)
    gvm = util.req_int(body, "guaranteed_verbal_mentions", minimum=0)
    cpo = util.req_int(body, "cross_promo_owed_count", minimum=0)
    rate = util.req_number(body, "rate_cents_per_second")
    if rate <= 0:
        raise errors.invalid_request("rate_cents_per_second must be > 0")
    return fee, gsec, gvm, cpo, rate


@bp.route("/proposals", methods=["POST"])
def create_proposal():
    middleware.require_roles("IntegrationManager")
    body = middleware.get_json_body()
    brief_id = body.get("brief_id")
    opp_id = body.get("opportunity_id")
    if not isinstance(brief_id, str):
        raise errors.invalid_request("Field 'brief_id' is required and must be a string")
    if not isinstance(opp_id, str):
        raise errors.invalid_request("Field 'opportunity_id' is required and must be a string")
    fee, gsec, gvm, cpo, rate = _validate_terms(body)
    brief = db.briefs.get(brief_id)
    if brief is None:
        raise errors.not_found("Brief not found")
    opp = db.opportunities.get(opp_id)
    if opp is None:
        raise errors.not_found("Opportunity not found")
    episode = db.episodes.get(opp["episode_id"])
    if opp["status"] != "IDENTIFIED":
        raise errors.ApiError(errors.ERR_OPPORTUNITY_UNAVAILABLE, 409,
                              "Opportunity is not IDENTIFIED")
    if episode is not None and episode["status"] in ("AIRED", "VERIFIED"):
        raise errors.ApiError(errors.ERR_EPISODE_ALREADY_AIRED, 409,
                              "Episode has already aired")
    if brief["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_BRIEF_NOT_OPEN, 409,
                              "Brief is not OPEN")
    brand = db.brands.get(brief["brand_id"])
    if brand is not None and brand["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_BRAND_SUSPENDED, 409, "Brand is SUSPENDED")
    _fee_floor_check(fee, gsec, rate)
    _budget_ceiling_check(fee, brief)
    ent = util.new_entity()
    ent.update({"brief_id": brief_id, "opportunity_id": opp_id,
                "proposed_fee_cents": fee, "guaranteed_seconds": gsec,
                "guaranteed_verbal_mentions": gvm, "cross_promo_owed_count": cpo,
                "rate_cents_per_second": rate, "terms_revision": 1, "status": "DRAFT"})
    db.proposals[ent["id"]] = ent
    opp["status"] = "PITCHED"
    util.touch(opp)
    calc.recompute_brief_remaining(brief_id)
    return response.success_object(proposal_view(ent), 201)


@bp.route("/proposals/<pid>", methods=["GET"])
def get_proposal(pid):
    middleware.require_roles(*middleware.ALL_ROLES)
    p = db.proposals.get(pid)
    if p is None:
        raise errors.not_found("Proposal not found")
    return response.success_object(proposal_view(p))


@bp.route("/proposals/<pid>/submit", methods=["POST"])
def submit_proposal(pid):
    middleware.require_roles("IntegrationManager")
    middleware.get_json_body(required=False)
    p = db.proposals.get(pid)
    if p is None:
        raise errors.not_found("Proposal not found")
    if p["status"] in ("REJECTED", "CONTRACTED", "WITHDRAWN"):
        raise errors.already_terminal("Proposal is terminal")
    if p["status"] != "DRAFT":
        raise errors.invalid_state("Proposal is not DRAFT")
    brief = db.briefs[p["brief_id"]]
    if brief["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_BRIEF_NOT_OPEN, 409, "Brief is not OPEN")
    opp = db.opportunities[p["opportunity_id"]]
    episode = db.episodes[opp["episode_id"]]
    if episode["status"] not in ("SCRIPT_REVIEW", "LOCKED"):
        raise errors.ApiError(errors.ERR_EPISODE_ALREADY_AIRED, 409,
                              "Episode is not in SCRIPT_REVIEW or LOCKED")
    _budget_ceiling_check(p["proposed_fee_cents"], brief, add_back=p["proposed_fee_cents"])
    p["status"] = "PRODUCTION_REVIEW"
    util.touch(p)
    calc.recompute_brief_remaining(p["brief_id"])
    return response.success_object(proposal_view(p))


@bp.route("/proposals/<pid>/production-decision", methods=["POST"])
def production_decision(pid):
    user_id, _ = middleware.require_roles("ProductionRep")
    body = middleware.get_json_body()
    decision = util.req_enum(body, "decision", DECISIONS)
    p = db.proposals.get(pid)
    if p is None:
        raise errors.not_found("Proposal not found")
    if p["status"] in ("REJECTED", "CONTRACTED", "WITHDRAWN"):
        raise errors.already_terminal("Proposal is terminal")
    if p["status"] != "PRODUCTION_REVIEW":
        raise errors.invalid_state("Proposal is not PRODUCTION_REVIEW")
    opp = db.opportunities[p["opportunity_id"]]
    episode = db.episodes[opp["episode_id"]]
    if user_id == episode["created_by_user_id"]:
        raise errors.segregation_of_duties(
            "Production decision maker must differ from the episode creator")
    if decision == "APPROVE":
        p["status"] = "NETWORK_REVIEW"
    elif decision == "REQUEST_REVISION":
        p["status"] = "REVISION_REQUESTED"
    else:
        p["status"] = "REJECTED"
        cascade.release_opportunity_to_identified(p)
    util.touch(p)
    calc.recompute_brief_remaining(p["brief_id"])
    return response.success_object(proposal_view(p))


@bp.route("/proposals/<pid>/network-decision", methods=["POST"])
def network_decision(pid):
    middleware.require_roles("NetworkStandardsReviewer")
    body = middleware.get_json_body()
    decision = util.req_enum(body, "decision", DECISIONS)
    p = db.proposals.get(pid)
    if p is None:
        raise errors.not_found("Proposal not found")
    if p["status"] in ("REJECTED", "CONTRACTED", "WITHDRAWN"):
        raise errors.already_terminal("Proposal is terminal")
    if p["status"] != "NETWORK_REVIEW":
        raise errors.invalid_state("Proposal is not NETWORK_REVIEW")
    if decision == "APPROVE":
        p["status"] = "APPROVED"
    elif decision == "REQUEST_REVISION":
        p["status"] = "REVISION_REQUESTED"
    else:
        p["status"] = "REJECTED"
        cascade.release_opportunity_to_identified(p)
    util.touch(p)
    calc.recompute_brief_remaining(p["brief_id"])
    return response.success_object(proposal_view(p))


@bp.route("/proposals/<pid>/revisions", methods=["POST"])
def revise_proposal(pid):
    middleware.require_roles("IntegrationManager")
    body = middleware.get_json_body()
    fee, gsec, gvm, cpo, rate = _validate_terms(body)
    if "expected_proposal_version" not in body:
        raise errors.invalid_request("Field 'expected_proposal_version' is required")
    expected = body["expected_proposal_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.invalid_request("Field 'expected_proposal_version' must be an integer")
    p = db.proposals.get(pid)
    if p is None:
        raise errors.not_found("Proposal not found")
    if p["status"] in ("REJECTED", "CONTRACTED", "WITHDRAWN"):
        raise errors.already_terminal("Proposal is terminal")
    if p["status"] != "REVISION_REQUESTED":
        raise errors.invalid_state("Proposal is not REVISION_REQUESTED")
    if expected != p["version"]:
        raise errors.stale_version("expected_proposal_version does not match proposal version")
    brief = db.briefs[p["brief_id"]]
    _fee_floor_check(fee, gsec, rate)
    _budget_ceiling_check(fee, brief, add_back=p["proposed_fee_cents"])
    p["proposed_fee_cents"] = fee
    p["guaranteed_seconds"] = gsec
    p["guaranteed_verbal_mentions"] = gvm
    p["cross_promo_owed_count"] = cpo
    p["rate_cents_per_second"] = rate
    p["terms_revision"] += 1
    p["status"] = "PRODUCTION_REVIEW"
    util.touch(p)
    calc.recompute_brief_remaining(p["brief_id"])
    return response.success_object(proposal_view(p))


@bp.route("/proposals/<pid>/withdraw", methods=["POST"])
def withdraw_proposal(pid):
    middleware.require_roles("IntegrationManager")
    middleware.get_json_body(required=False)
    p = db.proposals.get(pid)
    if p is None:
        raise errors.not_found("Proposal not found")
    if p["status"] in ("REJECTED", "CONTRACTED", "WITHDRAWN"):
        raise errors.already_terminal("Proposal is terminal")
    if p["status"] != "DRAFT":
        raise errors.invalid_state("Proposal is not DRAFT")
    p["status"] = "WITHDRAWN"
    cascade.release_opportunity_to_identified(p)
    util.touch(p)
    calc.recompute_brief_remaining(p["brief_id"])
    return response.success_object(proposal_view(p))


@bp.route("/proposals/<pid>/contract", methods=["POST"])
def create_contract_from_proposal(pid):
    middleware.require_roles("IntegrationManager")
    middleware.get_json_body(required=False)
    p = db.proposals.get(pid)
    if p is None:
        raise errors.not_found("Proposal not found")
    if p["status"] in ("REJECTED", "CONTRACTED", "WITHDRAWN"):
        raise errors.already_terminal("Proposal is terminal")
    if p["status"] != "APPROVED":
        raise errors.invalid_state("Proposal is not APPROVED")
    for c in db.contracts.values():
        if c["proposal_id"] == pid:
            raise errors.invalid_state("Proposal already has a contract")
    opp = db.opportunities[p["opportunity_id"]]
    provisional = calc.provisional_value_cents(
        p["proposed_fee_cents"], p["guaranteed_seconds"], p["rate_cents_per_second"],
        opp["estimated_exposure_seconds"])
    ent = util.new_entity()
    ent.update({
        "proposal_id": pid,
        "episode_id": opp["episode_id"],
        "base_fee_cents": p["proposed_fee_cents"],
        "guaranteed_seconds": p["guaranteed_seconds"],
        "guaranteed_verbal_mentions": p["guaranteed_verbal_mentions"],
        "rate_cents_per_second": p["rate_cents_per_second"],
        "cross_promo_owed_count": p["cross_promo_owed_count"],
        "provisional_value_cents": provisional,
        "bonus_cents": 0,
        "makegood_total_cents": 0,
        "outstanding_balance_cents": 0,
        "final_settlement_cents": None,
        "status": "PENDING_SIGNATURE",
    })
    db.contracts[ent["id"]] = ent
    p["status"] = "CONTRACTED"
    util.touch(p)
    cascade.reserve_opportunity(p)
    calc.recompute_brief_remaining(p["brief_id"])
    return response.success_object(contract_view(ent), 201)


@bp.route("/proposals/<pid>/contracts", methods=["GET"])
def list_proposal_contracts(pid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep",
                             "ProductionRep", "NetworkStandardsReviewer",
                             "VerificationAnalyst")
    p = db.proposals.get(pid)
    if p is None:
        raise errors.not_found("Proposal not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.contracts.values() if x["proposal_id"] == pid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([contract_view(x) for x in page], limit, offset, total)
