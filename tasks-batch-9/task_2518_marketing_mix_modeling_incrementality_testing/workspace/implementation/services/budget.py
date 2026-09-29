"""Waterfall budget optimisation (PRD section 3.8).

Two greedy passes over a 100000-cent step. The reallocation fee is computed from the
first pass's churn and is then pinned: the second pass never recomputes it.
"""

from decimal import Decimal

import db as store
from db import db, touch
from errors import ApiError
from services.market import require_posture_open, reset_scenario_to_baseline
from services.numeric import D, HUNDRED, ZERO, q0, q4

STEP_CENTS = 100000


def projected_units(allocated_cents, ceiling_units, half_point_cents, period_count):
    """n periods of the Hill response at an even per-period spend of allocated/n."""
    periods = D(period_count)
    per_period = D(allocated_cents) / periods
    if per_period == 0:
        return ZERO
    return periods * D(ceiling_units) * per_period / (per_period + D(half_point_cents))


def _greedy(budget_cents, enrolled, period_count):
    """enrolled: list of dicts with keys allocation, channel, code."""
    allocated = {}
    floors_total = 0
    for entry in enrolled:
        floor = entry["channel"]["min_spend_cents"]
        allocated[entry["allocation"]["id"]] = floor
        floors_total += floor
    remaining = budget_cents - floors_total
    if remaining < 0:
        raise ApiError("ERR_FLOORS_EXCEED_BUDGET",
                       "The enrolled channels' spend floors exceed the available budget.")
    while remaining >= STEP_CENTS:
        best = None
        for entry in enrolled:
            channel = entry["channel"]
            if channel["status"] == "PAUSED":
                continue
            current = allocated[entry["allocation"]["id"]]
            if current + STEP_CENTS > channel["max_spend_cents"]:
                continue
            gain = (projected_units(current + STEP_CENTS, channel["response_ceiling_units"],
                                    channel["saturation_half_point_cents"], period_count)
                    - projected_units(current, channel["response_ceiling_units"],
                                      channel["saturation_half_point_cents"], period_count))
            if best is None or gain > best[0]:
                best = (gain, entry)
        if best is None:
            break
        allocated[best[1]["allocation"]["id"]] += STEP_CENTS
        remaining -= STEP_CENTS
    return allocated


def _enrolled_rows(scenario):
    rows = []
    for allocation in store.allocations_of_scenario(scenario["id"]):
        channel = db.media_channels.get(allocation["channel_id"])
        code = channel["channel_code"] if channel else allocation["channel_id"]
        rows.append({"allocation": allocation, "channel": channel, "code": code})
    # Ascending channel_code is the deterministic tie-break for equal marginal gains.
    rows.sort(key=lambda entry: entry["code"])
    return rows


def perform_optimize(scenario):
    if scenario["status"] != "DRAFT":
        raise ApiError("ERR_BUDGET_SCENARIO_INVALID_STATE",
                       "Only a DRAFT scenario can be optimised.")
    run = db.model_runs.get(scenario["model_run_id"])
    if run is None or run["publication_status"] != "PUBLISHED" or run["fit_status"] != "FITTED":
        raise ApiError("ERR_MODEL_RUN_NOT_PUBLISHED",
                       "The referenced model run is no longer a published, fitted run.")
    market = db.markets[scenario["market_id"]]
    require_posture_open(market)

    enrolled = _enrolled_rows(scenario)
    if not enrolled:
        raise ApiError("ERR_NO_ALLOCATIONS")

    total_budget = scenario["total_budget_cents"]
    floors_total = sum(entry["channel"]["min_spend_cents"] for entry in enrolled)
    if floors_total > total_budget:
        raise ApiError("ERR_FLOORS_EXCEED_BUDGET",
                       "The enrolled channels' spend floors exceed the scenario budget.")
    baseline_total = sum(entry["allocation"]["baseline_spend_cents"] for entry in enrolled)
    if baseline_total != total_budget:
        raise ApiError("ERR_BASELINE_BUDGET_MISMATCH",
                       "The sum of baseline spend does not equal the scenario budget.")

    period_count = scenario["planning_period_count"]

    first_pass = _greedy(total_budget, enrolled, period_count)
    churn = 0
    for entry in enrolled:
        allocation = entry["allocation"]
        churn += abs(first_pass[allocation["id"]] - allocation["baseline_spend_cents"])
    fee_pct = D(scenario["reallocation_fee_pct"])
    fee_cents = q0(D(churn) * fee_pct / HUNDRED)

    second_pass = _greedy(total_budget - fee_cents, enrolled, period_count)

    allocated_total = 0
    shifted_total = 0
    projection_total = ZERO
    for entry in enrolled:
        allocation = entry["allocation"]
        channel = entry["channel"]
        amount = second_pass[allocation["id"]]
        shifted = abs(amount - allocation["baseline_spend_cents"])
        if amount == channel["min_spend_cents"]:
            binding = "FLOOR"
        elif amount == channel["max_spend_cents"]:
            binding = "CEILING"
        else:
            binding = "NONE"
        exact = projected_units(amount, channel["response_ceiling_units"],
                                channel["saturation_half_point_cents"], period_count)
        rounded = q4(exact)
        allocation["allocated_cents"] = amount
        allocation["shifted_cents"] = shifted
        allocation["constraint_binding"] = binding
        allocation["projected_contribution_units"] = rounded
        touch(allocation)
        allocated_total += amount
        shifted_total += shifted
        projection_total += rounded

    scenario["reallocation_fee_cents"] = fee_cents
    scenario["allocated_total_cents"] = allocated_total
    scenario["shifted_total_cents"] = shifted_total
    scenario["unallocated_cents"] = total_budget - fee_cents - allocated_total
    scenario["projected_contribution_units"] = projection_total
    scenario["projected_incremental_revenue_cents"] = q0(
        projection_total * D(run["unit_price_cents"]))
    scenario["status"] = "OPTIMIZED"
    touch(scenario)
    return scenario


def perform_revert(scenario):
    if scenario["status"] != "OPTIMIZED":
        raise ApiError("ERR_BUDGET_SCENARIO_INVALID_STATE",
                       "Only an OPTIMIZED scenario can be reverted.")
    reset_scenario_to_baseline(scenario)
    scenario["allocated_total_cents"] = scenario["total_budget_cents"]
    scenario["unallocated_cents"] = 0
    scenario["status"] = "DRAFT"
    touch(scenario)
    return scenario


def perform_approve(scenario, user_id):
    if user_id == scenario["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The scenario's author may not approve it.")
    if scenario["status"] != "OPTIMIZED":
        raise ApiError("ERR_BUDGET_SCENARIO_INVALID_STATE",
                       "Only an OPTIMIZED scenario can be approved.")
    run = db.model_runs.get(scenario["model_run_id"])
    if run is None or run["publication_status"] != "PUBLISHED":
        raise ApiError("ERR_MODEL_RUN_NOT_PUBLISHED",
                       "The referenced model run is no longer published.")
    if run["calibration_status"] not in ("NOT_REQUIRED", "CALIBRATED"):
        raise ApiError("ERR_CALIBRATION_STALE",
                       "The model run's calibration status is %s." % run["calibration_status"])
    scenario["status"] = "APPROVED"
    scenario["approved_by_user_id"] = user_id
    touch(scenario)
    return scenario


def refresh_allocation_totals(scenario):
    """Keep the conservation identity true from the moment allocation rows exist."""
    total = sum(a["allocated_cents"] for a in store.allocations_of_scenario(scenario["id"]))
    before = (scenario["allocated_total_cents"], scenario["unallocated_cents"])
    scenario["allocated_total_cents"] = total
    scenario["unallocated_cents"] = (scenario["total_budget_cents"]
                                     - scenario["reallocation_fee_cents"] - total)
    if before != (scenario["allocated_total_cents"], scenario["unallocated_cents"]):
        touch(scenario)
    return scenario
