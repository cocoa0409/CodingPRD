"""Plan endpoints (PRD 3.1, 3.3, 3.6, 3.8, 3.9)."""

from flask import Blueprint

import calc
import responses
import services
import validation as v
from auth import (FORECAST_ROLES, PLAN_SPONSOR, READ_ROLES, TRUSTEE, caller_id,
                  endpoint)
from clock import CLOCK
from db import DB, insert, serialize, touch
from errors import fail

bp = Blueprint("plans", __name__)

VESTING_SCHEDULES = ("CLIFF_3YR", "GRADED_6YR")
SERVICE_MEASUREMENT_METHODS = ("TERMINATION_DATE_MEASURE", "PLAN_YEAR_END_MEASURE")
FORFEITURE_POLICIES = ("REALLOCATE_PRO_RATA", "REDUCE_CONTRIBUTION")
DISTRIBUTION_POLICIES = ("LUMP_SUM", "FIVE_YEAR_INSTALLMENT")
SWEEP_MODES = ("STRICT_ORDER", "BEST_FIT")


@bp.post("/plans")
@endpoint([PLAN_SPONSOR])
def create_plan():
    body = v.body()
    record = {
        "plan_name": v.req_string(body, "plan_name"),
        "sponsor_name": v.req_string(body, "sponsor_name"),
        "plan_year": v.req_integer(body, "plan_year", minimum=1900, maximum=2999),
        "total_shares_outstanding": v.req_integer(body, "total_shares_outstanding", minimum=1),
        "annual_compensation_limit_cents": v.req_integer(
            body, "annual_compensation_limit_cents", required=False, default=34500000, minimum=1),
        "annual_additions_limit_cents": v.req_integer(
            body, "annual_additions_limit_cents", required=False, default=6900000, minimum=1),
        "vesting_schedule": v.req_enum(body, "vesting_schedule", VESTING_SCHEDULES),
        "service_measurement_method": v.req_enum(
            body, "service_measurement_method", SERVICE_MEASUREMENT_METHODS),
        "forfeiture_policy": v.req_enum(body, "forfeiture_policy", FORFEITURE_POLICIES),
        "distribution_policy": v.req_enum(body, "distribution_policy", DISTRIBUTION_POLICIES),
        "sweep_mode": v.req_enum(body, "sweep_mode", SWEEP_MODES, required=False,
                                 default="STRICT_ORDER"),
        "normal_retirement_age": v.req_integer(
            body, "normal_retirement_age", required=False, default=65, minimum=40, maximum=99),
        "diversification_min_age": v.req_integer(
            body, "diversification_min_age", required=False, default=55, minimum=40, maximum=99),
        "diversification_min_years": v.req_integer(
            body, "diversification_min_years", required=False, default=10, minimum=1),
        "plan_status": "OPEN",
        "total_plan_shares": 0,
        "suspense_shares": 0,
        "unallocated_released_shares": 0,
        "unallocated_forfeiture_shares": 0,
        "reacquired_shares": 0,
        "allocated_shares_total": 0,
        "current_share_price_cents": 0,
        "open_valuation_count": 0,
        "draft_run_count": 0,
        "repurchase_reserve_cents": 0,
        "repurchase_reserve_floor_cents": v.req_integer(
            body, "repurchase_reserve_floor_cents", required=False, default=0, minimum=0),
        "committed_repurchase_cents": 0,
        "cumulative_repurchase_funding_cents": 0,
        "cumulative_repurchase_settled_cents": 0,
        "repurchase_posture": "FUNDED",
        "forfeiture_sweep_threshold_shares": v.req_integer(
            body, "forfeiture_sweep_threshold_shares", required=False, default=0, minimum=0),
        "forfeiture_posture": "CLEAR",
        "frozen_reason": None,
    }
    plan = insert(DB.plans, record)
    return responses.ok(serialize(plan), 201)


@bp.get("/plans/<plan_id>")
@endpoint(READ_ROLES)
def read_plan(plan_id):
    plan = services.get_plan(plan_id)
    return responses.ok(serialize(plan))


@bp.post("/plans/<plan_id>/close-year")
@endpoint([PLAN_SPONSOR])
def close_year(plan_id):
    plan = services.get_plan(plan_id)
    services.check_not_frozen(plan)
    services.require_plan_status(plan, "OPEN")
    plan["plan_status"] = "VALUATION_PENDING"
    touch(plan)
    return responses.ok(serialize(plan))


@bp.post("/plans/<plan_id>/rollover")
@endpoint([PLAN_SPONSOR])
def rollover(plan_id):
    plan = services.get_plan(plan_id)
    services.check_not_frozen(plan)
    services.require_plan_status(plan, "ALLOCATION_LOCKED")
    if plan["forfeiture_posture"] != "CLEAR":
        fail("ERR_FORFEITURE_SWEEP_REQUIRED")

    plan["plan_status"] = "OPEN"
    plan["plan_year"] = plan["plan_year"] + 1
    # current_share_price_cents is deliberately left in force.
    for participant in services.participants_of_plan(plan["id"]):
        before = (participant["diversification_first_eligible_plan_year"],
                  participant["diversification_eligible"])
        services.refresh_diversification(participant, plan)
        after = (participant["diversification_first_eligible_plan_year"],
                 participant["diversification_eligible"])
        if before != after:
            touch(participant)
    touch(plan)
    return responses.ok(serialize(plan))


@bp.post("/plans/<plan_id>/freeze")
@endpoint([TRUSTEE])
def freeze(plan_id):
    # priority 3 (request shape) is judged before priority 4 (path existence)
    body = v.body()
    reason = v.req_string(body, "reason")

    plan = services.get_plan(plan_id)
    services.check_not_frozen(plan)
    services.freeze_plan(plan, reason)
    return responses.ok(serialize(plan))


@bp.post("/plans/<plan_id>/repurchase-funding")
@endpoint([TRUSTEE])
def repurchase_funding(plan_id):
    body = v.body()
    amount_cents = v.req_integer(body, "amount_cents", minimum=0)

    plan = services.get_plan(plan_id)
    services.check_not_frozen(plan)

    plan["repurchase_reserve_cents"] += amount_cents
    plan["cumulative_repurchase_funding_cents"] += amount_cents
    posture = services.recompute_repurchase_posture(plan)
    if posture == "FUNDED":
        services.restore_deferred_exercises(plan)
    touch(plan)
    return responses.ok(serialize(plan))


@bp.post("/plans/<plan_id>/repurchase-sweeps")
@endpoint([TRUSTEE])
def repurchase_sweep(plan_id):
    plan = services.get_plan(plan_id)
    services.check_not_frozen(plan)

    today = CLOCK.today()
    candidates = [x for x in services.exercises_of_plan(plan["id"])
                  if x["status"] in ("PENDING", "DEFERRED")
                  and calc.iso_to_date(x["window_close_date"]) >= today]
    candidates.sort(key=lambda x: (calc.PRIORITY_RANK[x["priority_class"]],
                                   x["exercise_date"], x["created_at"], x["_seq"]))

    spendable = plan["repurchase_reserve_cents"] - plan["repurchase_reserve_floor_cents"]
    if spendable < 0:
        spendable = 0

    funded_count = 0
    deferred_count = 0
    funded_cents_total = 0
    stopped_at_exercise_id = None

    index = 0
    while index < len(candidates):
        exercise = candidates[index]
        amount = exercise["exercise_amount_cents"]
        if amount <= spendable:
            exercise["status"] = "FUNDED"
            exercise["funded_cents"] = amount
            exercise["funded_by_user_id"] = caller_id()
            touch(exercise)
            spendable -= amount
            plan["repurchase_reserve_cents"] -= amount
            plan["committed_repurchase_cents"] += amount
            funded_count += 1
            funded_cents_total += amount
        else:
            exercise["status"] = "DEFERRED"
            touch(exercise)
            deferred_count += 1
            if plan["sweep_mode"] == "STRICT_ORDER":
                stopped_at_exercise_id = exercise["id"]
                for remaining in candidates[index + 1:]:
                    remaining["status"] = "DEFERRED"
                    touch(remaining)
                    deferred_count += 1
                break
        index += 1

    services.recompute_repurchase_posture(plan)
    touch(plan)

    return responses.ok({
        "funded_count": funded_count,
        "deferred_count": deferred_count,
        "funded_cents_total": funded_cents_total,
        "reserve_after_cents": plan["repurchase_reserve_cents"],
        "sweep_mode_applied": plan["sweep_mode"],
        "stopped_at_exercise_id": stopped_at_exercise_id,
    })


@bp.get("/plans/<plan_id>/repurchase-forecast")
@endpoint(FORECAST_ROLES)
def repurchase_forecast(plan_id):
    raw = v.query_str("horizon_years")
    if raw is None:
        horizon_years = calc.DEFAULT_HORIZON_YEARS
    else:
        try:
            horizon_years = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "horizon_years must be an integer.")
        if horizon_years < 0:
            fail("ERR_INVALID_REQUEST", "horizon_years may not be negative.")

    plan = services.get_plan(plan_id)

    current_year = CLOCK.today().year
    included = []
    for participant in services.participants_of_plan(plan["id"]):
        status = participant["status"]
        if status in ("TERMINATED", "RETIRED", "DECEASED"):
            included.append(participant)
        elif status == "ACTIVE":
            birth_year = calc.iso_to_date(participant["date_of_birth"]).year
            if birth_year + plan["normal_retirement_age"] <= current_year + horizon_years:
                included.append(participant)

    projected = sum(p["vested_shares"] * plan["current_share_price_cents"] for p in included)

    return responses.ok({
        "horizon_years": horizon_years,
        "participant_count": len(included),
        "projected_obligation_cents": projected,
        "committed_repurchase_cents": plan["committed_repurchase_cents"],
        "reserve_cents": plan["repurchase_reserve_cents"],
        "coverage_bps": calc.coverage_bps(plan["repurchase_reserve_cents"], projected),
    })
