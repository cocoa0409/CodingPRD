"""BusinessUnitPool routes: scorecard cycle, funding, calibration cycle."""

from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import (BUSINESS_UNIT_MANAGER, COMPENSATION_COMMITTEE,
                        FINANCE_CONTROLLER, HR_BUSINESS_PARTNER, PLAN_ADMIN,
                        authenticate, get_body, opt_percent, opt_string,
                        query_param, req_enum, req_id, req_percent, req_string)
from response import object_response
from routes.common import paginated
from serialize import pool_out
from services import lookup, rollup

bp = Blueprint("pools", __name__)

READ_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, BUSINESS_UNIT_MANAGER,
              HR_BUSINESS_PARTNER, FINANCE_CONTROLLER]
SETUP_STATUSES = ("DRAFT", "TARGETS_SET")
DECISIONS = {"CERTIFY", "RETURN"}
WITHIN = ("WITHIN_GUIDELINES", "NO_ELIGIBLE_PARTICIPANTS")


@bp.route("/bu-pools", methods=["POST"])
def create_pool():
    authenticate([PLAN_ADMIN])
    body = get_body()

    plan_id = req_id(body, "plan_id")
    business_unit_id = req_id(body, "business_unit_id")
    achievement = opt_percent(body, "bu_metric_achievement_pct",
                              default=Decimal("0.00"), minimum=0, maximum=200)
    narrative = opt_string(body, "scorecard_narrative")

    plan = lookup.plan(plan_id)
    lookup.business_unit(business_unit_id)

    if db.pool_for_unit(plan_id, business_unit_id) is not None:
        raise ApiError("ERR_DUPLICATE_RESOURCE",
                       "This business unit already has a pool in this plan")
    if plan["status"] not in SETUP_STATUSES:
        raise ApiError("ERR_PLAN_NOT_IN_SETUP")

    pool = db.base_record()
    pool.update({
        "plan_id": plan_id,
        "business_unit_id": business_unit_id,
        "bu_metric_achievement_pct": achievement,
        "scorecard_narrative": narrative,
        "calibration_status": "DRAFT",
        "eligible_target_cents": 0,
        "eligible_headcount": 0,
        "funded_cents": 0,
        "allocated_cents": 0,
        "available_cents": 0,
        "min_utilization_cents": 0,
        "utilization_pct": Decimal("0.00"),
        "top_tier_award_count": 0,
        "max_top_tier_count": 0,
        "distribution_status": "NO_ELIGIBLE_PARTICIPANTS",
        "calibration_returned_count": 0,
        "scorecard_certified_by_user_id": None,
    })
    db.bu_pools[pool["id"]] = pool
    return object_response(pool_out(pool), 201)


@bp.route("/bu-pools/<pool_id>/submit-scorecard", methods=["POST"])
def submit_scorecard(pool_id):
    caller = authenticate([BUSINESS_UNIT_MANAGER])
    pool = lookup.pool(pool_id)
    body = get_body()
    achievement = req_percent(body, "bu_metric_achievement_pct",
                              minimum=0, maximum=200)
    narrative = req_string(body, "scorecard_narrative")

    if caller.user_id != pool["business_unit_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNERSHIP",
                       "This manager does not own the pool's business unit")

    plan = lookup.plan(pool["plan_id"])
    if plan["status"] not in SETUP_STATUSES:
        raise ApiError("ERR_PLAN_NOT_IN_SETUP")
    if pool["calibration_status"] != "DRAFT":
        raise ApiError("ERR_POOL_STATE_INVALID",
                       "Scorecard submission requires a pool in DRAFT")

    pool["bu_metric_achievement_pct"] = achievement
    pool["scorecard_narrative"] = narrative
    pool["calibration_status"] = "SCORECARD_SUBMITTED"
    db.touch(pool)
    return object_response(pool_out(pool))


@bp.route("/bu-pools/<pool_id>/scorecard-decision", methods=["POST"])
def scorecard_decision(pool_id):
    caller = authenticate([COMPENSATION_COMMITTEE])
    pool = lookup.pool(pool_id)
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    opt_string(body, "decision_note")

    plan = lookup.plan(pool["plan_id"])
    if plan["status"] not in SETUP_STATUSES:
        raise ApiError("ERR_PLAN_NOT_IN_SETUP")
    if pool["calibration_status"] != "SCORECARD_SUBMITTED":
        raise ApiError("ERR_POOL_STATE_INVALID",
                       "Scorecard decision requires a pool in SCORECARD_SUBMITTED")

    if decision == "CERTIFY":
        pool["scorecard_certified_by_user_id"] = caller.user_id
        pool["calibration_status"] = "SCORECARD_CERTIFIED"
    else:
        pool["scorecard_certified_by_user_id"] = None
        pool["calibration_status"] = "DRAFT"
    db.touch(pool)
    return object_response(pool_out(pool))


@bp.route("/bu-pools/<pool_id>/submit-calibration", methods=["POST"])
def submit_calibration(pool_id):
    caller = authenticate([BUSINESS_UNIT_MANAGER])
    pool = lookup.pool(pool_id)
    body = get_body()
    narrative = opt_string(body, "scorecard_narrative")

    if caller.user_id != pool["business_unit_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNERSHIP",
                       "This manager does not own the pool's business unit")

    plan = lookup.plan(pool["plan_id"])
    if plan["status"] != "ALLOCATION_OPEN":
        raise ApiError("ERR_PLAN_NOT_IN_ALLOCATION")
    if pool["calibration_status"] not in ("FUNDED", "ALLOCATING"):
        raise ApiError("ERR_POOL_STATE_INVALID",
                       "Calibration submission requires a pool in FUNDED or ALLOCATING")
    if pool["top_tier_award_count"] > pool["max_top_tier_count"]:
        raise ApiError("ERR_TOP_TIER_CONCENTRATION")
    if pool["distribution_status"] not in WITHIN:
        raise ApiError("ERR_POOL_NOT_WITHIN_GUIDELINES")

    if narrative is not None:
        pool["scorecard_narrative"] = narrative
    pool["calibration_status"] = "CALIBRATION_SUBMITTED"
    db.touch(pool)
    return object_response(pool_out(pool))


@bp.route("/bu-pools/<pool_id>/calibration-decision", methods=["POST"])
def calibration_decision(pool_id):
    authenticate([PLAN_ADMIN])
    pool = lookup.pool(pool_id)
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    opt_string(body, "decision_note")

    plan = lookup.plan(pool["plan_id"])
    if plan["status"] not in ("ALLOCATION_OPEN", "CALIBRATION_REVIEW"):
        raise ApiError("ERR_PLAN_NOT_IN_ALLOCATION")

    if decision == "CERTIFY":
        if pool["calibration_status"] != "CALIBRATION_SUBMITTED":
            raise ApiError("ERR_POOL_STATE_INVALID",
                           "Calibration certification requires a pool in "
                           "CALIBRATION_SUBMITTED")
        if pool["distribution_status"] not in WITHIN:
            raise ApiError("ERR_POOL_NOT_WITHIN_GUIDELINES")
        for award in db.pool_awards(pool["id"]):
            if award["allocation_status"] == "PROPOSED":
                award["allocation_status"] = "CALIBRATED"
                db.touch(award)
        pool["calibration_status"] = "CALIBRATED"
        db.touch(pool)
    else:
        if pool["calibration_status"] not in ("CALIBRATION_SUBMITTED", "CALIBRATED"):
            raise ApiError("ERR_POOL_STATE_INVALID",
                           "Calibration return requires a pool in "
                           "CALIBRATION_SUBMITTED or CALIBRATED")
        for award in db.pool_awards(pool["id"]):
            if award["allocation_status"] == "CALIBRATED":
                award["allocation_status"] = "PROPOSED"
                db.touch(award)
        pool["calibration_returned_count"] += 1
        pool["calibration_status"] = "ALLOCATING"
        db.touch(pool)
        if plan["status"] == "CALIBRATION_REVIEW":
            plan["status"] = "ALLOCATION_OPEN"
            db.touch(plan)

    return object_response(pool_out(pool))


@bp.route("/bu-pools/<pool_id>", methods=["GET"])
def get_pool(pool_id):
    authenticate(READ_ROLES)
    return object_response(pool_out(lookup.pool(pool_id)))


@bp.route("/bu-pools", methods=["GET"])
def list_pools():
    authenticate(READ_ROLES)
    plan_id = query_param("plan_id")
    business_unit_id = query_param("business_unit_id")
    calibration_status = query_param("calibration_status")
    distribution_status = query_param("distribution_status")

    records = db.ordered(db.bu_pools)
    if plan_id is not None:
        records = [r for r in records if r["plan_id"] == plan_id]
    if business_unit_id is not None:
        records = [r for r in records if r["business_unit_id"] == business_unit_id]
    if calibration_status is not None:
        records = [r for r in records if r["calibration_status"] == calibration_status]
    if distribution_status is not None:
        records = [r for r in records
                   if r["distribution_status"] == distribution_status]
    return paginated(records, pool_out)
