from flask import Blueprint, request
from db import db, new_common_fields, touch
from errors import err
from middleware import get_caller, require_role
from response import object_response, array_response, parse_pagination, paginate
from validate import body, require_str, require_enum, require_list, require_line_items, require_int
import lookups
from services import calculations as calc
from services.recompute import recompute_policy_gross

claims_bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"UNPAID_RENT", "PROPERTY_DAMAGE", "BOTH"}


def _sum_line_items(line_items):
    return sum(li["amount_cents"] for li in line_items)


def _check_claim_ownership(caller, claim):
    if caller.role == "Landlord" and lookups.landlord_id_for_claim(claim) != caller.user_id:
        raise err("ERR_UNAUTHORIZED", "Caller does not own this claim.")
    if caller.role == "Renter" and lookups.renter_id_for_claim(claim) != caller.user_id:
        raise err("ERR_UNAUTHORIZED", "Caller does not own this claim.")


@claims_bp.post("/policies/<policy_id>/claims")
def file_claim(policy_id):
    caller = get_caller()
    require_role(caller, {"Landlord"})
    b = body()
    body_policy_id = require_str(b, "policy_id")
    claim_type = require_enum(b, "claim_type", CLAIM_TYPES)
    raw_line_items = require_list(b, "line_items", required=False, default=[])
    line_items = require_line_items(raw_line_items)

    policy = lookups.get_policy(policy_id)
    if body_policy_id != policy_id:
        # Redundant body FK must resolve too, per left-to-right/top-to-bottom existence rule.
        lookups.get_policy(body_policy_id)

    if lookups.landlord_id_for_policy(policy) != caller.user_id:
        raise err("ERR_UNAUTHORIZED", "Caller does not own the property behind this policy.")

    claim = {
        **new_common_fields(),
        "policy_id": policy_id,
        "claim_type": claim_type,
        "line_items": line_items,
        "total_claimed_amount_cents": _sum_line_items(line_items),
        "approved_amount_cents": None,
        "deductible_cents": None,
        "status": "UNDER_REVIEW",
        "reviewing_adjuster_id": None,
        "decision_notes": None,
    }
    db.claims[claim["id"]] = claim
    return object_response(claim, 201)


@claims_bp.get("/claims/<claim_id>")
def get_claim(claim_id):
    caller = get_caller()
    require_role(caller, {"Landlord", "ClaimsAdjuster", "ComplianceOfficer", "PlatformAdmin", "Renter"})
    claim = lookups.get_claim(claim_id)
    _check_claim_ownership(caller, claim)
    return object_response(claim)


@claims_bp.post("/claims/<claim_id>/info-transition")
def claim_info_transition(claim_id):
    caller = get_caller()
    require_role(caller, {"ClaimsAdjuster", "Landlord"})
    b = body()
    action = require_enum(b, "action", {"REQUEST_INFO", "SUBMIT_INFO"})
    decision_notes = require_str(b, "decision_notes", required=False, default=None)
    raw_line_items = require_list(b, "line_items", required=False, default=[])

    if action == "REQUEST_INFO" and caller.role != "ClaimsAdjuster":
        raise err("ERR_UNAUTHORIZED", "Only ClaimsAdjuster may request info.")
    if action == "SUBMIT_INFO" and caller.role != "Landlord":
        raise err("ERR_UNAUTHORIZED", "Only Landlord may submit info.")

    claim = lookups.get_claim(claim_id)
    _check_claim_ownership(caller, claim)

    if action == "REQUEST_INFO":
        if claim["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW.")
        claim["status"] = "NEEDS_INFO"
        claim["decision_notes"] = decision_notes
    else:
        if claim["status"] != "NEEDS_INFO":
            raise err("ERR_INVALID_STATE", "Claim is not NEEDS_INFO.")
        new_items = require_line_items(raw_line_items)
        claim["line_items"] = claim["line_items"] + new_items
        claim["total_claimed_amount_cents"] = _sum_line_items(claim["line_items"])
        claim["status"] = "UNDER_REVIEW"

    touch(claim)
    return object_response(claim)


@claims_bp.post("/claims/<claim_id>/decide")
def decide_claim(claim_id):
    caller = get_caller()
    require_role(caller, {"ClaimsAdjuster"})
    b = body()
    action = require_enum(b, "action", {"APPROVE", "DENY"})
    decision_notes = require_str(b, "decision_notes", required=False, default=None)

    claim = lookups.get_claim(claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW.")

    if action == "APPROVE":
        if len(claim["line_items"]) == 0:
            raise err("ERR_CLAIM_HAS_NO_LINE_ITEMS", "Claim has no line items.")
        policy = db.policies[claim["policy_id"]]
        if policy["status"] == "CANCELLED":
            raise err("ERR_INVALID_STATE", "Claim's policy is CANCELLED.")
        result = calc.claim_payout_calculation(claim["total_claimed_amount_cents"], policy["gross_available_coverage_cents"])
        if result["uncapped_amount_cents"] > policy["gross_available_coverage_cents"]:
            raise err("ERR_COVERAGE_LIMIT_EXCEEDED", "Payout the claim would generate exceeds gross available coverage.")

        claim["approved_amount_cents"] = result["approved_amount_cents"]
        claim["deductible_cents"] = result["deductible_cents"]
        claim["status"] = "APPROVED"
        claim["reviewing_adjuster_id"] = caller.user_id
        touch(claim)

        payout = {
            **new_common_fields(),
            "claim_id": claim["id"],
            "amount_cents": claim["approved_amount_cents"],
            "status": "PENDING",
            "disbursing_adjuster_id": None,
            "disbursed_at": None,
            "reversed_at": None,
            "reversal_reason": None,
        }
        db.payouts[payout["id"]] = payout

        recompute_policy_gross(policy)
        touch(policy)
    else:
        claim["status"] = "DENIED"
        claim["reviewing_adjuster_id"] = caller.user_id
        claim["decision_notes"] = decision_notes
        touch(claim)

    return object_response(claim)


@claims_bp.get("/claims/<claim_id>/payouts")
def list_claim_payouts(claim_id):
    caller = get_caller()
    require_role(caller, {"Landlord", "ClaimsAdjuster", "PlatformAdmin"})
    claim = lookups.get_claim(claim_id)
    _check_claim_ownership(caller, claim)

    limit, offset = parse_pagination(request.args)
    items = lookups.payouts_for_claim(claim["id"])
    window, total = paginate(items, limit, offset)
    return array_response(window, 200, limit, offset, total)


@claims_bp.post("/claims/<claim_id>/subrogation-cases")
def open_subrogation_case(claim_id):
    caller = get_caller()
    require_role(caller, {"ComplianceOfficer"})
    b = body()
    body_claim_id = require_str(b, "claim_id")
    original_demand_amount_cents = require_int(b, "original_demand_amount_cents", positive=True)

    claim = lookups.get_claim(claim_id)
    if body_claim_id != claim_id:
        lookups.get_claim(body_claim_id)

    payouts = lookups.payouts_for_claim(claim["id"])
    if not any(p["status"] == "DISBURSED" for p in payouts):
        raise err("ERR_SUBROGATION_REQUIRES_DISBURSED_PAYOUT", "Claim's payout has not been disbursed yet.")

    case = {
        **new_common_fields(),
        "claim_id": claim["id"],
        "original_demand_amount_cents": original_demand_amount_cents,
        "outstanding_balance_cents": original_demand_amount_cents,
        "status": "OPEN",
        "demand_sent_at": None,
    }
    db.subrogation_cases[case["id"]] = case
    return object_response(case, 201)


@claims_bp.get("/claims/<claim_id>/subrogation-cases")
def list_claim_subrogation_cases(claim_id):
    caller = get_caller()
    require_role(caller, {"ComplianceOfficer", "PlatformAdmin", "Renter"})
    claim = lookups.get_claim(claim_id)
    _check_claim_ownership(caller, claim)

    limit, offset = parse_pagination(request.args)
    items = lookups.subrogation_cases_for_claim(claim["id"])
    window, total = paginate(items, limit, offset)
    return array_response(window, 200, limit, offset, total)
