"""IntegrationContract endpoints."""
from decimal import Decimal

from flask import Blueprint

import db
import errors
import middleware
import response
import util
from services import calc, cascade

bp = Blueprint("contracts", __name__)


def contract_view(c):
    return {k: c[k] for k in ("id", "proposal_id", "episode_id", "base_fee_cents",
                              "guaranteed_seconds", "guaranteed_verbal_mentions",
                              "rate_cents_per_second", "cross_promo_owed_count",
                              "provisional_value_cents", "bonus_cents",
                              "makegood_total_cents", "outstanding_balance_cents",
                              "final_settlement_cents", "status",
                              "created_at", "updated_at", "version")}


def _contract_or_404(cid):
    c = db.contracts.get(cid)
    if c is None:
        raise errors.not_found("Contract not found")
    return c


@bp.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    middleware.require_roles(*middleware.ALL_ROLES)
    return response.success_object(contract_view(_contract_or_404(cid)))


@bp.route("/episodes/<eid>/contracts", methods=["GET"])
def list_episode_contracts(eid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep",
                             "ProductionRep", "NetworkStandardsReviewer",
                             "VerificationAnalyst")
    e = db.episodes.get(eid)
    if e is None:
        raise errors.not_found("Episode not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.contracts.values() if x["episode_id"] == eid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([contract_view(x) for x in page], limit, offset, total)


@bp.route("/contracts/<cid>/terms", methods=["PATCH"])
def amend_terms(cid):
    middleware.require_roles("IntegrationManager")
    body = middleware.get_json_body()
    fee = util.req_int(body, "base_fee_cents", minimum=0)
    if "expected_contract_version" not in body:
        raise errors.invalid_request("Field 'expected_contract_version' is required")
    expected = body["expected_contract_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.invalid_request("Field 'expected_contract_version' must be an integer")
    c = _contract_or_404(cid)
    if c["status"] == "TERMINATED":
        raise errors.already_terminal("Contract is TERMINATED")
    if c["status"] != "PENDING_SIGNATURE":
        raise errors.invalid_state("Contract is not PENDING_SIGNATURE")
    if expected != c["version"]:
        raise errors.stale_version("expected_contract_version does not match contract version")
    # fee floor then budget ceiling (own current hold added back)
    if Decimal(str(fee)) < Decimal(str(c["guaranteed_seconds"])) * Decimal(str(c["rate_cents_per_second"])):
        raise errors.ApiError(errors.ERR_FEE_BELOW_MINIMUM, 400,
                              "Fee below guaranteed_seconds * rate_cents_per_second floor")
    prop = db.proposals[c["proposal_id"]]
    brief = db.briefs[prop["brief_id"]]
    calc.recompute_brief_remaining(brief["id"])
    if fee > brief["remaining_budget_cents"] + c["base_fee_cents"]:
        raise errors.ApiError(errors.ERR_BUDGET_EXCEEDED, 422,
                              "Fee exceeds the brief's remaining budget")
    c["base_fee_cents"] = fee
    opp = db.opportunities[prop["opportunity_id"]]
    c["provisional_value_cents"] = calc.provisional_value_cents(
        fee, c["guaranteed_seconds"], c["rate_cents_per_second"],
        opp["estimated_exposure_seconds"])
    util.touch(c)
    calc.recompute_brief_remaining(brief["id"])
    return response.success_object(contract_view(c))


@bp.route("/contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    middleware.require_roles("IntegrationManager")
    middleware.get_json_body(required=False)
    c = _contract_or_404(cid)
    if c["status"] == "TERMINATED":
        raise errors.already_terminal("Contract is TERMINATED")
    if c["status"] != "PENDING_SIGNATURE":
        raise errors.invalid_state("Contract is not PENDING_SIGNATURE")
    episode = db.episodes[c["episode_id"]]
    if episode["status"] != "LOCKED":
        raise errors.ApiError(errors.ERR_EPISODE_NOT_LOCKED, 409,
                              "Contract activation requires episode status LOCKED")
    brand = cascade.contract_brand(c)
    granted = False
    for cl in db.clearances.values():
        if (cl["episode_id"] == c["episode_id"] and cl["status"] == "GRANTED"
                and brand is not None and cl["brand_id"] == brand["id"]):
            granted = True
            break
    if not granted:
        raise errors.ApiError(errors.ERR_CLEARANCE_REQUIRED, 409,
                              "No GRANTED clearance exists for this episode and brand")
    c["status"] = "ACTIVE"
    c["outstanding_balance_cents"] = c["base_fee_cents"]
    util.touch(c)
    # create cross-promo obligation
    owed = c["cross_promo_owed_count"]
    obl = util.new_entity()
    obl.update({"contract_id": cid, "owed_count": owed, "fulfilled_count": 0,
                "status": "FULFILLED" if owed == 0 else "OWED"})
    db.cross_promos[obl["id"]] = obl
    return response.success_object(contract_view(c))


@bp.route("/contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    middleware.require_roles("IntegrationManager")
    middleware.get_json_body(required=False)
    c = _contract_or_404(cid)
    if c["status"] == "TERMINATED":
        raise errors.already_terminal("Contract is TERMINATED")
    if c["status"] not in ("PENDING_SIGNATURE", "ACTIVE"):
        raise errors.invalid_state("Contract cannot be terminated from its current state")
    was_active = c["status"] == "ACTIVE"
    c["status"] = "TERMINATED"
    util.touch(c)
    prop = db.proposals[c["proposal_id"]]
    if was_active:
        for s in db.shipments.values():
            if (s["contract_id"] == cid
                    and s["status"] in ("PENDING", "DISPATCHED", "DELIVERED", "STAGED")):
                s["status"] = "RETURN_REQUESTED"
                util.touch(s)
                cascade.void_shipment_continuity(s["id"])
    cascade.unreserve_opportunity(prop)
    calc.recompute_brief_remaining(prop["brief_id"])
    cascade.evaluate_episode_bubbleup(c["episode_id"])
    return response.success_object(contract_view(c))


@bp.route("/contracts/<cid>/ledger", methods=["GET"])
def contract_ledger(cid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep",
                             "VerificationAnalyst")
    c = _contract_or_404(cid)
    return response.success_object({
        "base_fee_cents": c["base_fee_cents"],
        "bonus_cents": c["bonus_cents"],
        "makegood_total_cents": c["makegood_total_cents"],
        "outstanding_balance_cents": c["outstanding_balance_cents"],
        "provisional_value_cents": c["provisional_value_cents"],
        "final_settlement_cents": c["final_settlement_cents"],
    })
