"""Commission plan routes (PRD §3.2)."""

from flask import Blueprint

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_PLAN_INVALID_STATE,
    ERR_PLAN_IN_USE, ERR_STALE_PLAN_VERSION, ERR_PLAN_TIERS_INVALID,
    ERR_PCT_OUT_OF_RANGE,
)
from middleware import body, req_str, req_int, opt_int, req_num, opt_num, parse_enum_filter
from response import success_obj
from routes.helpers import guard, public, list_response, by_created
from services.common import new_id, stamp_new, touch
from services.enrollment import _snapshot_terms

bp = Blueprint("plans", __name__)

PLAN_STATUSES = {"DRAFT", "ACTIVE", "RETIRED"}


def _get_plan(plan_id):
    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "plan not found")
    return plan


def _validate_terms(data):
    """Parse + validate plan economic terms (PRD §3.2). Returns normalized dict."""
    name = req_str(data, "name")
    royalty_pct = req_num(data, "royalty_pct")
    royalty_cap_cents = req_int(data, "royalty_cap_cents")
    eo_fee_cents = req_int(data, "eo_fee_cents")
    transaction_fee_cents = req_int(data, "transaction_fee_cents")
    mentor_split_pct = opt_num(data, "mentor_split_pct", 0)
    mentor_deal_count = opt_int(data, "mentor_deal_count", 0)

    tiers_raw = data.get("tiers")
    if not isinstance(tiers_raw, list) or len(tiers_raw) == 0:
        raise ApiError(ERR_PLAN_TIERS_INVALID, 422, "tiers must be a non-empty list")
    tiers = []
    for t in tiers_raw:
        if not isinstance(t, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "each tier must be an object")
        thr = t.get("threshold_company_dollar_cents")
        pct = t.get("broker_split_pct")
        if not isinstance(thr, int) or isinstance(thr, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "tier threshold_company_dollar_cents must be an integer")
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, "tier broker_split_pct must be a number")
        tiers.append({"threshold_company_dollar_cents": thr, "broker_split_pct": pct})

    # Tier structure: strictly ascending thresholds, final broker_split_pct == 0
    for i in range(1, len(tiers)):
        if tiers[i]["threshold_company_dollar_cents"] <= tiers[i - 1]["threshold_company_dollar_cents"]:
            raise ApiError(ERR_PLAN_TIERS_INVALID, 422, "tier thresholds must be strictly ascending")
    if tiers[-1]["broker_split_pct"] != 0:
        raise ApiError(ERR_PLAN_TIERS_INVALID, 422,
                       "the final tier must carry broker_split_pct 0")

    # Fee amounts non-negative
    if eo_fee_cents < 0 or transaction_fee_cents < 0:
        raise ApiError(ERR_PLAN_TIERS_INVALID, 422, "plan fee amounts must be >= 0")

    # Percentage ranges
    if royalty_pct < 0 or royalty_pct > 1:
        raise ApiError(ERR_PCT_OUT_OF_RANGE, 422, "royalty_pct must lie in [0,1]")
    if mentor_split_pct is not None and (mentor_split_pct < 0 or mentor_split_pct > 1):
        raise ApiError(ERR_PCT_OUT_OF_RANGE, 422, "mentor_split_pct must lie in [0,1]")
    for t in tiers:
        if t["broker_split_pct"] < 0 or t["broker_split_pct"] > 1:
            raise ApiError(ERR_PCT_OUT_OF_RANGE, 422, "broker_split_pct must lie in [0,1]")

    return {
        "name": name,
        "royalty_pct": royalty_pct,
        "royalty_cap_cents": royalty_cap_cents,
        "eo_fee_cents": eo_fee_cents,
        "transaction_fee_cents": transaction_fee_cents,
        "mentor_split_pct": mentor_split_pct if mentor_split_pct is not None else 0,
        "mentor_deal_count": mentor_deal_count if mentor_deal_count is not None else 0,
        "tiers": tiers,
    }


@bp.route("/brokerage/plans", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def create_plan(user_id, role):
    terms = _validate_terms(body())
    plan = {"id": new_id(), **terms, "status": "DRAFT"}
    stamp_new(plan)
    plan["_versions"] = {plan["version"]: _snapshot_terms(plan)}
    db.plans[plan["id"]] = plan
    return success_obj(public(plan), status=201)


@bp.route("/brokerage/plans/<planId>", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def get_plan(user_id, role, planId):
    return success_obj(public(_get_plan(planId)))


@bp.route("/brokerage/plans", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def list_plans(user_id, role):
    status = parse_enum_filter("status", PLAN_STATUSES)
    items = list(db.plans.values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(by_created(items))


@bp.route("/brokerage/plans/<planId>", methods=["PUT"])
@guard(roles=["BrokerAdmin"])
def put_plan(user_id, role, planId):
    plan = _get_plan(planId)
    data = body()
    expected = data.get("expected_plan_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_plan_version is required and must be an integer")

    # OCC (step 7) precedes state validity (step 8)
    if expected != plan["version"]:
        raise ApiError(ERR_STALE_PLAN_VERSION, 412,
                       "expected_plan_version does not match the plan's current version")
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_PLAN_INVALID_STATE, 409, "only a DRAFT plan is editable")

    terms = _validate_terms(data)
    plan.update(terms)
    touch(plan)
    plan["_versions"][plan["version"]] = _snapshot_terms(plan)
    return success_obj(public(plan))


@bp.route("/brokerage/plans/<planId>/activate", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def activate_plan(user_id, role, planId):
    plan = _get_plan(planId)
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_PLAN_INVALID_STATE, 409, "only a DRAFT plan can be activated")
    plan["status"] = "ACTIVE"
    touch(plan)
    plan["_versions"][plan["version"]] = _snapshot_terms(plan)
    return success_obj(public(plan))


@bp.route("/brokerage/plans/<planId>/retire", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def retire_plan(user_id, role, planId):
    plan = _get_plan(planId)
    if plan["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_PLAN_INVALID_STATE, 409, "plan is already RETIRED")
    for e in db.enrollments.values():
        if e["plan_id"] == planId and e["status"] in ("ACTIVE", "SCHEDULED"):
            raise ApiError(ERR_PLAN_IN_USE, 409,
                           "an ACTIVE or SCHEDULED enrollment references this plan")
    plan["status"] = "RETIRED"
    touch(plan)
    return success_obj(public(plan))
