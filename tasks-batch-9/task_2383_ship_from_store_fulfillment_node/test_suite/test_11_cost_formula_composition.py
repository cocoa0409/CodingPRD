"""Composition of the parcel-cost and order-cost formulas.

Three compositions are pinned here: the per-line rounding order inside the ship
charge, the tier lookup that keys the network overhead fee on the pre-fee
subtotal, and the nested minimum that produces a candidate's coverage figure.
"""

import pytest

from test_helpers import (
    assert_cost_comparison,
    commit_routing,
    cost_comparison,
    find_assignment,
    find_assignment_lines,
    find_routing_candidates,
    read_assignment,
    read_order,
    read_order_line,
    read_routing_run,
    setup_network,
    setup_order_with_lines,
)

CLOCK = "2026-08-03T09:00:00Z"


# ---------------------------------------------------------------- preambles


def _expedited_two_line_order_at_s3(order_code: str) -> dict:
    """One node at origin zone 2, two SKUs of different weight and package
    class, and an EXPEDITED order to zone 4 whose first demand line is the
    light SKU and whose second is the heavy one.

    Returns ``store``, ``sku_a``, ``sku_b``, ``order``, ``lines``, ``run``,
    ``assignment`` and ``candidates`` (iteration 1).
    """
    net = setup_network(
        node_presets=("S3",),
        sku_presets=("SKU-A", "SKU-B"),
        clock=CLOCK,
        stock=[("S3", "SKU-A", 12, 2), ("S3", "SKU-B", 8, 1)],
    )
    store = net["stores"]["S3"]
    sku_a = net["skus"]["SKU-A"]
    sku_b = net["skus"]["SKU-B"]

    built = setup_order_with_lines(
        [(sku_b["id"], 1, 1900), (sku_a["id"], 3, 4500)],
        order_code=order_code,
        customer_ref="C-2",
        destination_zone=4,
        service_level="EXPEDITED",
        promised_ship_by_utc="2026-08-03T14:00:00Z",
    )
    order = built["order"]

    run = commit_routing(order["id"])
    assignment = find_assignment(order_id=order["id"], store_id=store["id"])
    candidates = find_routing_candidates(routing_run_id=run["id"], iteration=1)

    return {
        "store": store,
        "sku_a": sku_a,
        "sku_b": sku_b,
        "order": read_order(order["id"]),
        "lines": built["lines"],
        "run": run,
        "assignment": assignment,
        "candidates": candidates,
    }


def _labour_bound_order_at_s6(order_code: str = "O-2003") -> dict:
    """One node whose staffed labour, not its stock, is the binding constraint,
    and a single-line GROUND order to the node's own zone for 20 units."""
    net = setup_network(
        node_presets=("S6",),
        sku_presets=("SKU-A",),
        clock=CLOCK,
        stock=[("S6", "SKU-A", 25, 0)],
    )
    store = net["stores"]["S6"]
    sku = net["skus"]["SKU-A"]

    built = setup_order_with_lines(
        [(sku["id"], 20, 4500)],
        order_code=order_code,
        customer_ref="C-3",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T16:00:00Z",
    )
    order = built["order"]
    line = built["lines"][0]

    run = commit_routing(order["id"])
    assignment = find_assignment(order_id=order["id"], store_id=store["id"])

    return {
        "store": store,
        "sku": sku,
        "order": read_order(order["id"]),
        "line": read_order_line(line["id"]),
        "run": read_routing_run(run["id"]),
        "assignment": assignment,
        "candidates": find_routing_candidates(routing_run_id=run["id"], iteration=1),
    }


# ======================================================================
# Per-line ship rounding before the sum
# ======================================================================


class TestPerLineShipRoundingBeforeSum:
    def test_expedited_two_line_assignment_prices_ship_cost_per_rounded_line(self):
        """PRD §3.8: "For each line, the line weight is the served SKU's `unit_weight_grams` multiplied by the units on that line; the number of weight steps is that weight divided by a 500-gram step and rounded up to a whole number of steps; the raw line charge is the zone base charge plus 25 cents per weight step; that raw charge is multiplied by the service multiplier — 1.00 for a `GROUND` order and 1.35 for an `EXPEDITED` one — and the product is rounded half-up to whole cents."
        PRD §3.8: "The assignment's ship cost is the sum of those already-rounded per-line charges."
        PRD §3.8: "It is emphatically *not* the sum of raw line charges multiplied by the service multiplier and rounded once at the end."
        PRD §3.8: "That gap indexes a base shipping charge — 320 cents at a gap of 0, then 380, 445, 520, 610, 700, 800 and 900 cents at gaps of 1 through 7 respectively."
        PRD §3.8: "**Labour cost** is the charged labour minutes multiplied by the node's `labor_rate_cents_per_minute`, rounded up to the next whole cent."
        PRD §3.8: "**Packaging cost** is the base cost of the charged package type — 45 cents for a `POLY_MAILER`, 85 for a `SMALL_BOX`, 130 for a `MEDIUM_BOX` and 190 for a `LARGE_BOX` — plus 15 cents of dunnage per charged unit."
        PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."
        PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."
        PRD §3.8: "Its charged units are `assigned_units`, and its charged package is `derived_package_type`."

        Design: Difficulty/combinatorial_formula/per_line_ship_rounding_before_sum_on_expedited_two_line_assignment
        """
        ctx = _expedited_two_line_order_at_s3("O-2001")
        assignment = ctx["assignment"]

        assert assignment["assigned_units"] == 4, (
            "both demand lines are covered at the single node, so the assignment "
            f"holds 4 units, got {assignment['assigned_units']}"
        )
        assert assignment["provisional_cost_cents"] == 1955, (
            "each line's expedited charge is rounded before the sum, so ship cost "
            "is 1405 and the assignment prices at 1955 — never 1954, which is what "
            "rounding the summed raw charges once at the end would produce; got "
            f"{assignment['provisional_cost_cents']}"
        )

    def test_expedited_two_line_assignment_charges_the_standard_and_derived_package(self):
        """PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."
        PRD §3.5: "`derived_package_type` is the package the provisional cost assumes: take the heaviest `package_class` among the allocation's SKUs by package rank and map it, so `SMALL` becomes `SMALL_BOX`, `MEDIUM` becomes `MEDIUM_BOX` and `LARGE` becomes `LARGE_BOX`."
        PRD §3.5: "Alongside the assignment, one assignment line is created per demand line served, each carrying `assignment_id`, `order_line_id` and `units_assigned` — immutable after creation — with `units_picked` and `units_cancelled` both starting at 0."

        Design: Difficulty/combinatorial_formula/per_line_ship_rounding_before_sum_on_expedited_two_line_assignment
        """
        ctx = _expedited_two_line_order_at_s3("O-2001")
        assignment = ctx["assignment"]

        assert assignment["derived_package_type"] == "MEDIUM_BOX", (
            "the heaviest package_class of the allocation is MEDIUM (SKU-A), which "
            f"maps to MEDIUM_BOX, got {assignment['derived_package_type']}"
        )
        assert assignment["labor_minutes_reserved"] == pytest.approx(18.00, abs=0.01), (
            "the node's standard is 10 minutes per order plus 2 minutes for each of "
            f"4 units, got {assignment['labor_minutes_reserved']}"
        )

        lines = find_assignment_lines(assignment["id"])
        assert len(lines) == 2, (
            f"one assignment line per served demand line, got {len(lines)}"
        )
        assert sorted(row["units_assigned"] for row in lines) == [1, 3], (
            "the assignment lines carry 1 unit of the light SKU and 3 of the heavy "
            f"one, got {[row['units_assigned'] for row in lines]}"
        )

    def test_expedited_two_line_candidate_estimate_matches_the_per_line_rounded_cost(self):
        """PRD §3.4: "`cost_estimate_cents` is the provisional fulfillment cost of exactly that planned allocation at that node, computed as in §3.8."
        PRD §3.4: "Its `coverage_units` is the smallest of four numbers: its promise-able units, its capacity units left, its labour units left, and the total remaining demand."
        PRD §3.4: "`coverage_ratio` is `coverage_units` divided by the total remaining demand, rounded half-up to four decimal places."
        PRD §3.4: "`delivery_days` is the transit time from this node to the order's destination, read from the zone-gap table: a gap of 0 gives 1 day, a gap of 1 or 2 gives 2 days, a gap of 3 gives 3 days, a gap of 4 gives 4 days, a gap of 5 or 6 gives 5 days, and a gap of 7 gives 6 days, where the gap is the absolute difference between the order's `destination_zone` and the node's `origin_zone`; on an `EXPEDITED` order that figure is reduced by one day but never below the one-day minimum."
        PRD §3.4: "The cost factor takes a ceiling of 2000 cents minus `cost_estimate_cents`, divides by the 1600-cent span between that ceiling and a floor of 400 cents, and clamps the result into 0 to 1 inclusive."
        PRD §3.4: "Those factors are weighted 45 for coverage, 25 for cost, 20 for speed and 10 for health and summed; a node whose `node_status` is `PROBATION` then has a penalty of 8 points subtracted; and the result is rounded half-up to two decimal places."
        PRD §3.4: "The winner's `selected` flag is set to true and its `assigned_units` is set equal to its `coverage_units`."

        Design: Difficulty/combinatorial_formula/per_line_ship_rounding_before_sum_on_expedited_two_line_assignment
        """
        ctx = _expedited_two_line_order_at_s3("O-2001")
        candidates = ctx["candidates"]
        assert len(candidates) == 1, (
            f"the network holds one node, so iteration 1 persists one candidate row, "
            f"got {len(candidates)}"
        )
        candidate = candidates[0]

        assert candidate["cost_estimate_cents"] == 1955, (
            "the candidate's estimate is the same per-line-rounded provisional cost "
            f"as the assignment's, got {candidate['cost_estimate_cents']}"
        )
        assert candidate["coverage_units"] == 4, (
            f"the node covers all 4 remaining units, got {candidate['coverage_units']}"
        )
        assert candidate["coverage_ratio"] == pytest.approx(1.0000, abs=0.01), (
            f"4 covered of 4 remaining is a ratio of 1.0000, got {candidate['coverage_ratio']}"
        )
        assert candidate["delivery_days"] == 1, (
            "a zone gap of 2 gives 2 days, reduced by one for an EXPEDITED order, "
            f"got {candidate['delivery_days']}"
        )
        assert candidate["routing_score"] == pytest.approx(74.50, abs=0.01), (
            "the cost factor is driven by the 1955-cent estimate, so the blended "
            f"score is 74.50, got {candidate['routing_score']}"
        )
        assert candidate["selected"] is True, (
            "the only eligible candidate wins the iteration and is flagged selected"
        )

    def test_expedited_two_line_order_rolls_the_per_line_rounded_cost_into_the_order(self):
        """PRD §3.8: "The pre-fee subtotal is that component sum, plus a split penalty of 175 cents for each parcel beyond the first, plus a reroute overhead of 90 cents multiplied by the order's `reroute_attempt_count`."
        PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
        PRD §3.8: "The **provisional** variant, kept live in `provisional_cost_cents` after every routing change and every assignment status change, includes the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — that is, the five non-terminal statuses plus `SHIPPED` — using each one's `provisional_cost_cents`."
        PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."
        PRD §3.8: "The order's `cost_index_bps` uses `final_cost_cents` once that is set and `provisional_cost_cents` before then."
        PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."

        Design: Difficulty/combinatorial_formula/per_line_ship_rounding_before_sum_on_expedited_two_line_assignment
        """
        ctx = _expedited_two_line_order_at_s3("O-2001")
        order = ctx["order"]

        assert order["routing_status"] == "ROUTED", (
            "the single node covered every open unit, so the order is ROUTED, got "
            f"{order['routing_status']}"
        )
        assert order["provisional_cost_cents"] == 2072, (
            "a single-parcel component sum of 1955 carries no split penalty and no "
            f"reroute overhead, so the store cost is 2072, got {order['provisional_cost_cents']}"
        )
        assert order["cost_index_bps"] == 8893, (
            "2072 cents against the zone-4 baseline for 4 units is 8893 basis "
            f"points, got {order['cost_index_bps']}"
        )


# ======================================================================
# The network fee tier is keyed on the pre-fee subtotal
# ======================================================================


class TestNetworkFeeTierKeyedOnPreFeeSubtotal:
    def test_cost_comparison_keys_the_fee_rate_on_the_pre_fee_subtotal(self):
        """PRD §3.8: "The overhead fee rate is then keyed on the pre-fee subtotal: 6.0 percent when the subtotal is strictly below 2000 cents, 4.5 percent when it is strictly below 5000 cents, and 3.0 percent at or above 5000 cents."
        PRD §3.8: "**That tier lookup order is pinned**: the rate is read from the pre-fee subtotal, it is never re-read from the total after the fee has been added, and the fee never re-tiers itself."
        PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
        PRD §3.8: "The pre-fee subtotal is that component sum, plus a split penalty of 175 cents for each parcel beyond the first, plus a reroute overhead of 90 cents multiplied by the order's `reroute_attempt_count`."
        PRD §3.8: "Its body reports the `order_id`, the `variant` used — `FINAL` when the order's `fulfillment_status` is `SHIPPED` and `PROVISIONAL` otherwise — the `parcel_count`, the `component_sum_cents`, the `split_penalty_cents` and `reroute_overhead_cents` actually applied, the `pre_fee_subtotal_cents`, the `network_fee_rate` used and the resulting `network_fee_cents`, the `store_cost_cents`, the `dc_baseline_cost_cents`, the `cost_index_bps` and the `savings_vs_dc_cents`."

        Design: Difficulty/combinatorial_formula/network_fee_tier_keyed_on_pre_fee_subtotal_not_store_cost
        """
        ctx = _expedited_two_line_order_at_s3("O-2002")
        comparison = cost_comparison(ctx["order"]["id"])
        assert_cost_comparison(comparison)

        assert comparison["variant"] == "PROVISIONAL", (
            "nothing has shipped, so fulfillment_status is not SHIPPED and the read "
            f"uses the PROVISIONAL variant, got {comparison['variant']}"
        )
        assert comparison["component_sum_cents"] == 1955, (
            "the one included assignment contributes its 1955-cent provisional "
            f"cost, got {comparison['component_sum_cents']}"
        )
        assert comparison["pre_fee_subtotal_cents"] == 1955, (
            "one parcel means no split penalty and no reroutes mean no overhead, so "
            f"the pre-fee subtotal is the component sum, got {comparison['pre_fee_subtotal_cents']}"
        )
        assert comparison["network_fee_rate"] == pytest.approx(0.060, abs=0.001), (
            "the pre-fee subtotal 1955 is strictly below 2000 cents, so the rate is "
            f"6.0 percent, got {comparison['network_fee_rate']}"
        )
        assert comparison["network_fee_cents"] == 117, (
            "1955 cents at 6.0 percent rounds half-up to 117 cents; re-keying the "
            "rate off the resulting store cost would have produced 88 instead, got "
            f"{comparison['network_fee_cents']}"
        )
        assert comparison["store_cost_cents"] == 2072, (
            "the store cost is 1955 plus the 117-cent fee, which lands above the "
            "2000-cent tier ceiling without ever re-tiering the fee — 2043 would be "
            f"the store-cost-keyed answer, got {comparison['store_cost_cents']}"
        )

    def test_cost_comparison_index_and_savings_follow_the_pre_fee_keyed_store_cost(self):
        """PRD §3.8: "The distribution-centre baseline is a per-zone handling figure plus a per-unit charge: 1450 cents for `destination_zone` 1, then 1560, 1700, 1850, 2010, 2180, 2360 and 2550 cents for zones 2 through 8, plus 120 cents multiplied by the order's `total_units`."
        PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."
        PRD §3.8: "Savings versus the distribution centre are the baseline minus the store cost, and may of course be negative."
        PRD §3.8: "**That tier lookup order is pinned**: the rate is read from the pre-fee subtotal, it is never re-read from the total after the fee has been added, and the fee never re-tiers itself."

        Design: Difficulty/combinatorial_formula/network_fee_tier_keyed_on_pre_fee_subtotal_not_store_cost
        """
        ctx = _expedited_two_line_order_at_s3("O-2002")
        comparison = cost_comparison(ctx["order"]["id"])

        assert comparison["dc_baseline_cost_cents"] == 2330, (
            "zone 4 handling of 1850 cents plus 120 cents for each of 4 units is "
            f"2330, got {comparison['dc_baseline_cost_cents']}"
        )
        assert comparison["cost_index_bps"] == 8893, (
            "the store cost 2072 against the 2330-cent baseline is 8893 basis "
            f"points, got {comparison['cost_index_bps']}"
        )
        assert comparison["savings_vs_dc_cents"] == 258, (
            "2330 minus the 2072-cent store cost leaves 258 cents of savings, got "
            f"{comparison['savings_vs_dc_cents']}"
        )


# ======================================================================
# coverage_units is a nested minimum
# ======================================================================


class TestCoverageUnitsNestedMinimum:
    def test_candidate_coverage_units_is_bound_by_the_labour_floor_division(self):
        """PRD §3.4: "Its `coverage_units` is the smallest of four numbers: its promise-able units, its capacity units left, its labour units left, and the total remaining demand."
        PRD §3.4: "the node's labour units left is at least 1, computed by taking `staffed_labor_minutes`, subtracting `reserved_labor_minutes`, subtracting `labor_standard_minutes_per_order`, dividing by `pick_labor_minutes_per_unit` and discarding any fraction — otherwise `LABOR_EXHAUSTED`"
        PRD §3.4: "the node's capacity units left, being `daily_unit_capacity` minus `units_committed_epoch`, is at least 1 — otherwise `CAPACITY_EXHAUSTED`"
        PRD §3.4: "the node's promise-able units, being the sum over the SKUs still in remaining demand of the smaller of that SKU's remaining demand and that node's `available_to_promise_units` for it (treated as 0 when the node stocks no row for the SKU), is at least 1 — otherwise `NO_ATP`"
        PRD §3.4: "`coverage_ratio` is `coverage_units` divided by the total remaining demand, rounded half-up to four decimal places."
        PRD §3.4: "The winner's `selected` flag is set to true and its `assigned_units` is set equal to its `coverage_units`."

        Design: Difficulty/combinatorial_formula/coverage_units_is_three_way_nested_minimum
        """
        ctx = _labour_bound_order_at_s6()
        candidates = ctx["candidates"]
        assert len(candidates) == 1, (
            f"iteration 1 evaluates the network's single node, got {len(candidates)}"
        )
        candidate = candidates[0]

        assert candidate["coverage_units"] == 18, (
            "promise-able units 20, capacity units left 100 and remaining demand 20 "
            "all lose to the labour units left of 18, got "
            f"{candidate['coverage_units']}"
        )
        assert candidate["coverage_ratio"] == pytest.approx(0.9000, abs=0.01), (
            f"18 covered of 20 remaining is 0.9000, got {candidate['coverage_ratio']}"
        )
        assert candidate["assigned_units"] == 18, (
            "the winner's assigned_units equals its coverage_units, got "
            f"{candidate['assigned_units']}"
        )

    def test_candidate_cost_and_score_price_only_the_labour_bound_coverage(self):
        """PRD §3.4: "`cost_estimate_cents` is the provisional fulfillment cost of exactly that planned allocation at that node, computed as in §3.8."
        PRD §3.4: "`delivery_days` is the transit time from this node to the order's destination, read from the zone-gap table: a gap of 0 gives 1 day, a gap of 1 or 2 gives 2 days, a gap of 3 gives 3 days, a gap of 4 gives 4 days, a gap of 5 or 6 gives 5 days, and a gap of 7 gives 6 days, where the gap is the absolute difference between the order's `destination_zone` and the node's `origin_zone`; on an `EXPEDITED` order that figure is reduced by one day but never below the one-day minimum."
        PRD §3.4: "The cost factor takes a ceiling of 2000 cents minus `cost_estimate_cents`, divides by the 1600-cent span between that ceiling and a floor of 400 cents, and clamps the result into 0 to 1 inclusive."
        PRD §3.4: "Those factors are weighted 45 for coverage, 25 for cost, 20 for speed and 10 for health and summed; a node whose `node_status` is `PROBATION` then has a penalty of 8 points subtracted; and the result is rounded half-up to two decimal places."
        PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."
        PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."

        Design: Difficulty/combinatorial_formula/coverage_units_is_three_way_nested_minimum
        """
        ctx = _labour_bound_order_at_s6()
        candidate = ctx["candidates"][0]
        assignment = read_assignment(ctx["assignment"]["id"])

        assert candidate["cost_estimate_cents"] == 3245, (
            "the estimate prices the 18-unit allocation at a zone gap of 0, not the "
            f"full 20 units, got {candidate['cost_estimate_cents']}"
        )
        assert candidate["delivery_days"] == 1, (
            "the node's origin zone equals the destination zone, a gap of 0, giving "
            f"1 day, got {candidate['delivery_days']}"
        )
        assert candidate["routing_score"] == pytest.approx(64.68, abs=0.01), (
            "a 0.9000 coverage factor, a cost factor clamped to 0 by the 3245-cent "
            f"estimate and a full speed factor blend to 64.68, got {candidate['routing_score']}"
        )
        assert assignment["assigned_units"] == 18, (
            f"the assignment is created for the covered 18 units, got {assignment['assigned_units']}"
        )
        assert assignment["provisional_cost_cents"] == 3245, (
            "the assignment carries the same 18-unit provisional cost as the "
            f"candidate estimate, got {assignment['provisional_cost_cents']}"
        )
        assert assignment["labor_minutes_reserved"] == pytest.approx(60.00, abs=0.01), (
            "6 minutes per order plus 3 minutes for each of 18 units exhausts the "
            f"node's 60 staffed minutes exactly, got {assignment['labor_minutes_reserved']}"
        )

    def test_labour_bound_coverage_leaves_the_residual_units_open_on_the_run(self):
        """PRD §3.4: "When the loop ends, `unfulfillable_units` records whatever remaining demand is left, and `selected_store_count` and `planned_split_count` both equal the number of nodes selected."
        PRD §3.4: "`candidate_count` records how many candidate rows this run persisted across all iterations."
        PRD §3.4: "If it ended because a candidate pool came up empty, the units simply stay in `open_units` and the order's `routing_status` is re-derived."
        PRD §3.4: "Otherwise a `COMMIT` run's `status` is `COMMITTED`."
        PRD §3.4: "the node is not among the run's `excluded_store_ids` and has not already been selected earlier in this run — otherwise `EXCLUDED_BY_PRIOR_FAILURE`"

        Design: Difficulty/combinatorial_formula/coverage_units_is_three_way_nested_minimum
        """
        ctx = _labour_bound_order_at_s6()
        run = ctx["run"]

        assert run["status"] == "COMMITTED", (
            f"the run selected a node and created its assignment, got {run['status']}"
        )
        assert run["selected_store_count"] == 1, (
            f"exactly one node was selected, got {run['selected_store_count']}"
        )
        assert run["unfulfillable_units"] == 2, (
            "20 demanded less the 18 the labour cap allowed leaves 2 unfulfillable, "
            f"got {run['unfulfillable_units']}"
        )
        assert run["candidate_count"] == 2, (
            "iteration 1 persists the winning evaluation and iteration 2 persists a "
            "second row for the already-selected node before the loop stops, got "
            f"{run['candidate_count']}"
        )

    def test_labour_bound_residual_stays_open_on_the_line_and_order(self):
        """PRD §3.4: "If it ended because a candidate pool came up empty, the units simply stay in `open_units` and the order's `routing_status` is re-derived."
        PRD §3.2: "A demand line's `open_units` is always its `quantity` less `assigned_units`, less `shipped_units`, less `cancelled_units`, less `dc_fallback_units`."
        PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."
        PRD §2.9: "At the order level, `total_units` equals the sum of every demand line's `quantity`, and `unassigned_units` equals the sum of every demand line's `open_units`."
        PRD §3.8: "The overhead fee rate is then keyed on the pre-fee subtotal: 6.0 percent when the subtotal is strictly below 2000 cents, 4.5 percent when it is strictly below 5000 cents, and 3.0 percent at or above 5000 cents."
        PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."

        Design: Difficulty/combinatorial_formula/coverage_units_is_three_way_nested_minimum
        """
        ctx = _labour_bound_order_at_s6()
        line = ctx["line"]
        order = ctx["order"]

        assert line["assigned_units"] == 18, (
            f"the labour-bound allocation holds 18 of the line's units, got {line['assigned_units']}"
        )
        assert line["open_units"] == 2, (
            "the residual stays open because the second iteration found no eligible "
            f"node, got {line['open_units']}"
        )
        assert line["dc_fallback_units"] == 0, (
            "the three-split ceiling was never reached, so nothing was handed to the "
            f"distribution centre, got {line['dc_fallback_units']}"
        )
        assert order["routing_status"] == "PARTIALLY_ROUTED", (
            "18 of 20 units are covered with no failed assignment to reroute, got "
            f"{order['routing_status']}"
        )
        assert order["unassigned_units"] == 2, (
            f"the order mirrors the line's 2 open units, got {order['unassigned_units']}"
        )
        assert order["provisional_cost_cents"] == 3391, (
            "a pre-fee subtotal of 3245 falls in the 4.5 percent band, so the store "
            f"cost is 3391, got {order['provisional_cost_cents']}"
        )
        assert order["cost_index_bps"] == 7979, (
            "3391 cents against the zone-4 baseline for 20 units is 7979 basis "
            f"points, got {order['cost_index_bps']}"
        )
