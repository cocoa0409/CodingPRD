"""Routing waterfall (PRD 3.4 / calculations.routing_node_selection_waterfall,
routing_candidate_evaluation)."""
import clock
from constants import (
    COST_REFERENCE_HIGH, COST_REFERENCE_LOW, COVERAGE_WEIGHT, COST_WEIGHT,
    HEALTH_WEIGHT, LIVE_STATUSES, MAX_REROUTE_ATTEMPTS, MAX_SPLITS_PER_ORDER,
    PROBATION_SCORE_PENALTY, RELEASED_STATUSES, SPEED_REFERENCE_HIGH,
    SPEED_REFERENCE_LOW, SPEED_WEIGHT, TRANSIT_DAYS_BY_ZONE_DELTA,
)
from db import db, new_row, sorted_rows
from services.assignments import (
    create_assignment, derived_package_type, provisional_cost, release_assignment,
)
from services.costs import order_cost_breakdown, zone_delta
from services.derive import (
    assignments_of_order, inventory_for, open_window, order_lines_of, recompute_all,
)
from util import D, clamp01, div, floor_int, minute_of_day, n2, n4, rhu


def create_run(order, mode, initiated_by, excluded_store_ids):
    return new_row("routing_runs", {
        "order_id": order["id"],
        "mode": mode,
        "initiated_by": initiated_by,
        "excluded_store_ids": list(excluded_store_ids),
        "candidate_count": 0,
        "selected_store_count": 0,
        "planned_split_count": 0,
        "projected_cost_cents": 0,
        "projected_dc_cost_cents": 0,
        "projected_cost_index_bps": 0,
        "unfulfillable_units": 0,
        "guardrail_overridden": False,
        "status": "EVALUATED",
    })


def transit_days(order, store):
    days = TRANSIT_DAYS_BY_ZONE_DELTA[zone_delta(order, store)]
    if order["service_level"] == "EXPEDITED":
        days = max(1, days - 1)
    return days


def _routing_score(store, coverage_ratio, cost_estimate_cents, delivery_days):
    coverage_factor = D(coverage_ratio)
    cost_factor = rhu(clamp01(div(D(COST_REFERENCE_HIGH) - D(cost_estimate_cents),
                                 D(COST_REFERENCE_HIGH) - D(COST_REFERENCE_LOW))), 4)
    speed_factor = rhu(clamp01(div(D(SPEED_REFERENCE_HIGH) - D(delivery_days),
                                  D(SPEED_REFERENCE_HIGH) - D(SPEED_REFERENCE_LOW))), 4)
    health_factor = rhu(div(D(store["eligibility_score"]), 100), 4)
    raw = (D(COVERAGE_WEIGHT) * coverage_factor
           + D(COST_WEIGHT) * cost_factor
           + D(SPEED_WEIGHT) * speed_factor
           + D(HEALTH_WEIGHT) * health_factor)
    if store["node_status"] == "PROBATION":
        raw = raw - D(PROBATION_SCORE_PENALTY)
    return n2(raw)


def _new_candidate(run, store, iteration, fields):
    payload = {
        "routing_run_id": run["id"],
        "store_id": store["id"],
        "iteration": iteration,
        "eligible": False,
        "ineligible_reason": None,
        "coverage_units": 0,
        "coverage_ratio": 0.0,
        "cost_estimate_cents": 0,
        "delivery_days": 0,
        "routing_score": None,
        "rank": None,
        "selected": False,
        "assigned_units": 0,
    }
    payload.update(fields)
    candidate = new_row("candidates", payload)
    return candidate


def _evaluate(run, order, store, iteration, remaining, lines, selected_store_ids):
    """Eight pinned filter clauses; the first failure is the recorded reason."""
    total_remaining = sum(remaining.values())
    remaining_by_sku = {}
    for line_id, units in remaining.items():
        if units <= 0:
            continue
        sku_id = db.order_lines[line_id]["sku_id"]
        remaining_by_sku[sku_id] = remaining_by_sku.get(sku_id, 0) + units

    reason = None
    capacity_left = 0
    labor_left = 0
    atp_by_sku = {}
    atp_units = 0

    if store["id"] in run["excluded_store_ids"] or store["id"] in selected_store_ids:
        reason = "EXCLUDED_BY_PRIOR_FAILURE"
    elif store["node_status"] not in ("ELIGIBLE", "PROBATION"):
        reason = "NODE_NOT_ELIGIBLE"
    elif open_window(store["id"]) is None:
        reason = "NODE_NOT_ELIGIBLE"
    elif minute_of_day(clock.now()) > store["cutoff_utc_minutes"]:
        reason = "CUTOFF_PASSED"
    else:
        capacity_left = store["daily_unit_capacity"] - store["units_committed_epoch"]
        if capacity_left < 1:
            reason = "CAPACITY_EXHAUSTED"
        else:
            labor_left = floor_int(div(
                D(store["staffed_labor_minutes"]) - D(store["reserved_labor_minutes"])
                - D(store["labor_standard_minutes_per_order"]),
                D(store["pick_labor_minutes_per_unit"])))
            if labor_left < 1:
                reason = "LABOR_EXHAUSTED"
            else:
                hazmat_needed = any(db.skus[sku_id]["hazmat_flag"]
                                    for sku_id in remaining_by_sku)
                if hazmat_needed and not store["hazmat_certified"]:
                    reason = "HAZMAT_NOT_CERTIFIED"
                else:
                    for sku_id in remaining_by_sku:
                        inv = inventory_for(store["id"], sku_id)
                        atp_by_sku[sku_id] = inv["available_to_promise_units"] if inv else 0
                    atp_units = sum(min(remaining_by_sku[s], atp_by_sku[s])
                                    for s in remaining_by_sku)
                    if atp_units < 1:
                        reason = "NO_ATP"

    if reason is not None:
        return _new_candidate(run, store, iteration, {
            "eligible": False, "ineligible_reason": reason,
        }), None

    coverage_units = min(atp_units, capacity_left, labor_left, total_remaining)

    allocation = []
    allocated = 0
    sku_left = dict(atp_by_sku)
    for line in lines:
        if allocated >= coverage_units:
            break
        line_remaining = remaining.get(line["id"], 0)
        if line_remaining <= 0:
            continue
        take = min(line_remaining, sku_left.get(line["sku_id"], 0),
                   coverage_units - allocated)
        if take > 0:
            allocation.append((line, take))
            allocated += take
            sku_left[line["sku_id"]] = sku_left.get(line["sku_id"], 0) - take
    coverage_units = allocated

    coverage_ratio = n4(div(coverage_units, total_remaining))
    package_type = derived_package_type(allocation)
    cost_estimate = provisional_cost(order, store, allocation, coverage_units,
                                     package_type)
    delivery_days = transit_days(order, store)
    score = _routing_score(store, coverage_ratio, cost_estimate, delivery_days)

    candidate = _new_candidate(run, store, iteration, {
        "eligible": True,
        "ineligible_reason": None,
        "coverage_units": coverage_units,
        "coverage_ratio": coverage_ratio,
        "cost_estimate_cents": cost_estimate,
        "delivery_days": delivery_days,
        "routing_score": score,
        "rank": None,
        "selected": False,
        "assigned_units": 0,
    })
    return candidate, allocation


def execute_run(run, order, base_generation=0):
    """Runs the waterfall, writes the run's projections, returns an outcome dict."""
    mode = run["mode"]
    commit_mode = mode == "COMMIT"

    # Supersede step: a COMMIT run tears down the order's still-unaccepted
    # assignments before any evaluation so their units re-enter the demand pool.
    if commit_mode:
        for assignment in assignments_of_order(order["id"]):
            if assignment["status"] == "ASSIGNED":
                release_assignment(assignment, "CANCELLED", "SUPERSEDED",
                                   superseded_by=run["id"])
        recompute_all()

    lines = order_lines_of(order["id"])
    remaining = {l["id"]: l["open_units"] for l in lines if l["open_units"] > 0}
    stores = sorted_rows(db.stores.values())

    selected_store_ids = []
    selected_candidates = []
    created_assignments = []
    candidate_total = 0
    iteration = 1
    empty_pool_at_first_iteration = False

    while sum(remaining.values()) > 0 and len(selected_store_ids) < MAX_SPLITS_PER_ORDER:
        total_remaining = sum(remaining.values())
        candidates = []
        allocations = {}
        for store in stores:
            candidate, allocation = _evaluate(run, order, store, iteration, remaining,
                                              lines, selected_store_ids)
            candidate_total += 1
            candidates.append(candidate)
            if allocation is not None:
                allocations[candidate["id"]] = allocation
        eligible = [c for c in candidates if c["eligible"]]
        if not eligible:
            if iteration == 1:
                empty_pool_at_first_iteration = True
            break
        eligible.sort(key=lambda c: (-D(c["routing_score"]), c["cost_estimate_cents"],
                                     -c["coverage_units"],
                                     db.stores[c["store_id"]]["_seq"]))
        for index, candidate in enumerate(eligible):
            candidate["rank"] = index + 1
        full_coverage = [c for c in eligible if c["coverage_units"] == total_remaining]
        winner = full_coverage[0] if full_coverage else eligible[0]
        winner["selected"] = True
        winner["assigned_units"] = winner["coverage_units"]
        selected_candidates.append(winner)
        allocation = allocations[winner["id"]]

        if commit_mode:
            generation = 0 if run["initiated_by"] == "PLANNER" else base_generation + 1
            created_assignments.append(create_assignment(
                order, db.stores[winner["store_id"]], run, allocation, generation))

        for line, units in allocation:
            remaining[line["id"]] = remaining.get(line["id"], 0) - units
        remaining = {k: v for k, v in remaining.items() if v > 0}
        selected_store_ids.append(winner["store_id"])
        iteration += 1
        if commit_mode:
            recompute_all()

    unfulfillable = sum(remaining.values())

    # Three-split ceiling reached with leftover demand: hand the rest to the DC.
    dc_fallback_units = 0
    if (commit_mode and unfulfillable > 0
            and len(selected_store_ids) >= MAX_SPLITS_PER_ORDER):
        for line_id, units in remaining.items():
            db.order_lines[line_id]["dc_fallback_units"] += units
            dc_fallback_units += units
        recompute_all()

    run["candidate_count"] = candidate_total
    run["selected_store_count"] = len(selected_store_ids)
    run["planned_split_count"] = len(selected_store_ids)
    run["unfulfillable_units"] = unfulfillable

    recompute_all()
    live = [a for a in assignments_of_order(order["id"])
            if a["status"] not in RELEASED_STATUSES]
    components = [a["provisional_cost_cents"] for a in live]
    parcels = len(live)
    if not commit_mode:
        components = components + [c["cost_estimate_cents"] for c in selected_candidates]
        parcels += len(selected_candidates)
    projection = order_cost_breakdown(order, components, parcels,
                                      order["reroute_attempt_count"])
    run["projected_cost_cents"] = projection["store_cost_cents"]
    run["projected_dc_cost_cents"] = projection["dc_baseline_cost_cents"]
    run["projected_cost_index_bps"] = projection["cost_index_bps"]

    if not commit_mode:
        run["status"] = "EVALUATED"
    elif len(selected_store_ids) == 0:
        run["status"] = "NO_ELIGIBLE_NODE"
    else:
        run["status"] = "COMMITTED"

    return {
        "created": created_assignments,
        "dc_fallback_units": dc_fallback_units,
        "empty_pool_at_first_iteration": empty_pool_at_first_iteration,
        "unfulfillable": unfulfillable,
        "selected_store_ids": selected_store_ids,
    }


def strand_open_units(order):
    """Convert an order's still-open units into dc_fallback_units."""
    moved = 0
    for line in order_lines_of(order["id"]):
        if line["open_units"] > 0:
            moved += line["open_units"]
            line["dc_fallback_units"] += line["open_units"]
    if moved:
        recompute_all()
    return moved


def base_generation_for(order):
    generations = [a["reroute_generation"] for a in assignments_of_order(order["id"])
                   if a["status"] in ("REJECTED", "CANCELLED", "SHORT_PICKED")]
    return max(generations) if generations else 0
