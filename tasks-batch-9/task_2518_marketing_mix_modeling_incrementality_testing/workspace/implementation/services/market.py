"""Market aggregates, data posture and the posture-driven scenario cascade.

PRD section 2.9 (posture ladder), 3.1 (aggregates), 3.3 (thaw) and 3.8 (freeze).
"""

from decimal import Decimal

import db as store
from db import db, touch
from errors import ApiError
from services.numeric import D, HUNDRED, q2, q4

ASSIGNED_STATES = ("TREATMENT", "CONTROL", "WASHOUT")


def posture_of(market):
    """First match wins. Nothing else may reorder these three tests."""
    market_id = market["id"]
    windows = store.windows_of_market(market_id)
    for window in windows:
        if window["status"] == "REOPENED":
            return "FROZEN"
    published = store.published_run_of_market(market_id)
    if published is None:
        return "RESTRICTED"
    if published["calibration_status"] == "STALE":
        return "RESTRICTED"
    if not any(w["status"] == "SEALED" for w in windows):
        return "RESTRICTED"
    return "OPEN"


def _aggregates(market):
    cells = store.cells_of_market(market["id"])
    celled = sum(c["population"] for c in cells)
    held_out = sum(c["population"] for c in cells if c["assignment_state"] in ASSIGNED_STATES)
    total = market["total_population"]
    pct = q2(HUNDRED * D(held_out) / D(total)) if total else Decimal("0.00")
    return celled, held_out, pct


def sync_market(market, force=False):
    """Recompute the market's derived fields; fire the posture cascade on a change."""
    before = (
        market["celled_population"],
        market["held_out_population"],
        market["held_out_population_pct"],
        market["published_model_run_id"],
        market["data_posture"],
    )
    celled, held_out, pct = _aggregates(market)
    published = store.published_run_of_market(market["id"])
    market["celled_population"] = celled
    market["held_out_population"] = held_out
    market["held_out_population_pct"] = pct
    market["published_model_run_id"] = published["id"] if published else None
    new_posture = posture_of(market)
    old_posture = before[4]
    market["data_posture"] = new_posture
    after = (
        market["celled_population"],
        market["held_out_population"],
        market["held_out_population_pct"],
        market["published_model_run_id"],
        market["data_posture"],
    )
    if force or before != after:
        touch(market)
    if new_posture != old_posture:
        if new_posture == "OPEN":
            _thaw_frozen_scenarios(market)
        elif old_posture == "OPEN":
            _freeze_optimized_scenarios(market)
    return market


def reset_scenario_to_baseline(scenario):
    """Restore a scenario and its allocation rows to their pre-optimisation figures."""
    total = 0
    for allocation in store.allocations_of_scenario(scenario["id"]):
        allocation["allocated_cents"] = allocation["baseline_spend_cents"]
        allocation["shifted_cents"] = 0
        allocation["constraint_binding"] = "NONE"
        allocation["projected_contribution_units"] = Decimal("0.0000")
        total += allocation["baseline_spend_cents"]
        touch(allocation)
    scenario["reallocation_fee_cents"] = 0
    scenario["shifted_total_cents"] = 0
    scenario["allocated_total_cents"] = total
    scenario["unallocated_cents"] = scenario["total_budget_cents"] - total
    scenario["projected_contribution_units"] = Decimal("0.0000")
    scenario["projected_incremental_revenue_cents"] = 0


def _freeze_optimized_scenarios(market):
    for scenario in store.scenarios_of_market(market["id"]):
        if scenario["status"] == "OPTIMIZED":
            reset_scenario_to_baseline(scenario)
            scenario["status"] = "FROZEN"
            touch(scenario)


def _thaw_frozen_scenarios(market):
    for scenario in store.scenarios_of_market(market["id"]):
        if scenario["status"] == "FROZEN":
            reset_scenario_to_baseline(scenario)
            scenario["status"] = "DRAFT"
            touch(scenario)


def require_posture_not_frozen(market):
    if market["data_posture"] == "FROZEN":
        raise ApiError("ERR_MARKET_POSTURE_BLOCKED",
                       "The market's data posture is FROZEN.")


def require_posture_open(market):
    if market["data_posture"] != "OPEN":
        raise ApiError("ERR_MARKET_POSTURE_BLOCKED",
                       "The market's data posture must be OPEN (it is %s)."
                       % market["data_posture"])
