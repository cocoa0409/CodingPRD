"""WarrantyClaim endpoints."""

from flask import Blueprint, request

import db
from errors import (ApiError, err_not_found, err_invalid_request,
                    err_invalid_state, err_unauthorized)
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import stamp_new, touch, serialize, audit
from services.calculations import TIER_COVERAGE

bp = Blueprint("warranty_claims", __name__)


def _load_claim(cid):
    wc = db.warranty_claims.get(cid)
    if wc is None:
        raise err_not_found("WarrantyClaim not found")
    return wc


@bp.post("/stairlift-ops/agreements/<aid>/warranty-claims")
def create_claim(aid):
    user_id, role = require_role("Customer", "ClaimsAdjuster", "PlatformAdmin")
    ag = db.agreements.get(aid)
    if ag is None:
        raise err_not_found("Agreement not found")
    if role == "Customer" and user_id != ag["customer_id"]:
        raise err_unauthorized()
    if ag["status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE to file a claim")
    body = get_json_body(["service_plan_id", "claim_kind", "claimed_cents"])
    sp_id = body["service_plan_id"]
    kind = body["claim_kind"]
    claimed = body["claimed_cents"]
    if not isinstance(sp_id, str):
        raise err_invalid_request("service_plan_id must be a string")
    if kind not in ("MECHANICAL", "ELECTRICAL", "STRUCTURAL", "WEAR_AND_TEAR"):
        raise err_invalid_request("claim_kind invalid")
    if isinstance(claimed, bool) or not isinstance(claimed, int):
        raise err_invalid_request("claimed_cents must be an integer")
    sp = db.service_plans.get(sp_id)
    if sp is None:
        raise err_not_found("ServicePlan not found")
    wc = {
        "agreement_id": aid,
        "service_plan_id": sp_id,
        "claim_kind": kind,
        "claimed_cents": claimed,
        "status": "SUBMITTED",
        "approved_cents": 0,
        "denial_reason": None,
    }
    stamp_new(wc)
    db.warranty_claims[wc["id"]] = wc
    return success_object(serialize(wc), 201)


@bp.get("/stairlift-ops/agreements/<aid>/warranty-claims")
def list_claims(aid):
    user_id, role = require_role("PlatformAdmin", "ClaimsAdjuster", "Customer",
                                 "InstallCoordinator")
    ag = db.agreements.get(aid)
    if ag is None:
        raise err_not_found("Agreement not found")
    if role == "Customer" and user_id != ag["customer_id"]:
        raise err_unauthorized()
    limit, offset = get_pagination()
    status = request.args.get("status")
    items = sorted(
        (w for w in db.warranty_claims.values() if w["agreement_id"] == aid),
        key=lambda w: w["created_at"])
    if status:
        items = [w for w in items if w["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(w) for w in page], limit, offset, total)


@bp.get("/stairlift-ops/warranty-claims/<cid>")
def get_claim(cid):
    user_id, role = require_role("PlatformAdmin", "ClaimsAdjuster", "Customer")
    wc = _load_claim(cid)
    if role == "Customer":
        ag = db.agreements.get(wc["agreement_id"])
        if ag is None or user_id != ag["customer_id"]:
            raise err_unauthorized()
    return success_object(serialize(wc))


@bp.post("/stairlift-ops/warranty-claims/<cid>/review")
def review_claim(cid):
    user_id, role = require_role("ClaimsAdjuster")
    wc = _load_claim(cid)
    if wc["status"] != "SUBMITTED":
        raise err_invalid_state("WarrantyClaim must be SUBMITTED to review")
    wc["status"] = "UNDER_REVIEW"
    touch(wc)
    audit("WarrantyClaim", wc["id"], "CLAIM_UNDER_REVIEW", role, {})
    return success_object(serialize(wc))


@bp.post("/stairlift-ops/warranty-claims/<cid>/adjudicate")
def adjudicate_claim(cid):
    user_id, role = require_role("ClaimsAdjuster")
    wc = _load_claim(cid)
    if wc["status"] != "UNDER_REVIEW":
        raise err_invalid_state("WarrantyClaim must be UNDER_REVIEW to adjudicate")
    body = get_json_body(["decision"])
    decision = body["decision"]
    if decision not in ("APPROVED", "DENIED"):
        raise err_invalid_request("decision must be APPROVED or DENIED")
    ag = db.agreements.get(wc["agreement_id"])
    sp = db.service_plans.get(wc["service_plan_id"])
    if decision == "DENIED":
        reason = body.get("denial_reason")
        if not isinstance(reason, str) or not reason:
            raise err_invalid_request("denial_reason required for DENIED")
        wc["status"] = "DENIED"
        wc["denial_reason"] = reason
        touch(wc)
        audit("WarrantyClaim", wc["id"], "CLAIM_DENIED", role, {})
        return success_object(serialize(wc))
    # APPROVED: four fiscal gates
    if sp is None or sp["status"] != "ACTIVE":
        raise ApiError("ERR_SERVICE_PLAN_INACTIVE", 402,
                       "ServicePlan must be ACTIVE")
    if ag is not None and ag.get("liability_waiver_signed") \
            and wc["claim_kind"] == "WEAR_AND_TEAR":
        raise ApiError("ERR_WAIVER_BLOCKS_CLAIM", 422,
                       "Liability waiver blocks WEAR_AND_TEAR claims")
    if wc["claim_kind"] not in TIER_COVERAGE[sp["tier"]]:
        raise ApiError("ERR_CLAIM_KIND_NOT_COVERED", 402,
                       "claim_kind not covered by plan tier")
    if sp["coverage_used_cents"] + wc["claimed_cents"] > sp["coverage_cap_cents"]:
        raise ApiError("ERR_COVERAGE_CAP_EXCEEDED", 402,
                       "Coverage cap would be exceeded")
    headroom = sp["coverage_cap_cents"] - sp["coverage_used_cents"]
    wc["approved_cents"] = min(wc["claimed_cents"], headroom)
    wc["status"] = "APPROVED"
    touch(wc)
    audit("WarrantyClaim", wc["id"], "CLAIM_APPROVED", role,
          {"approved_cents": wc["approved_cents"]})
    return success_object(serialize(wc))


@bp.post("/stairlift-ops/warranty-claims/<cid>/pay")
def pay_claim(cid):
    user_id, role = require_role("ClaimsAdjuster")
    wc = _load_claim(cid)
    if wc["status"] != "APPROVED":
        raise err_invalid_state("WarrantyClaim must be APPROVED to pay")
    wc["status"] = "PAID"
    touch(wc)
    sp = db.service_plans.get(wc["service_plan_id"])
    if sp is not None:
        sp["coverage_used_cents"] = sp.get("coverage_used_cents", 0) + wc["approved_cents"]
        touch(sp)
    audit("WarrantyClaim", wc["id"], "CLAIM_PAID", role,
          {"approved_cents": wc["approved_cents"]})
    return success_object(serialize(wc))
