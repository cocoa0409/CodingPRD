"""Costing and scoring: the order-level cost rollup read, epoch-scoped window
metrics, the billable-labour floor on the final variant, half-cent network fees,
the pick-deadline clamp and the weighted routing score.

Every test builds its whole world from an empty database and then pins the
serialised figures the PRD's formulas are required to produce.
"""

from datetime import datetime

import pytest

from test_helpers import (
    PLANNER,
    accept,
    api_client,
    assert_cost_comparison,
    close_windows,
    commit_routing,
    cost_comparison,
    find_assignment,
    find_routing_candidates,
    pack,
    pick_full,
    provisional_routing,
    read_assignment,
    read_order,
    read_routing_run,
    read_store,
    schedule_pickup,
    set_clock,
    setup_committed_assignment,
    setup_network,
    setup_order_with_lines,
    setup_shipped_assignment,
    ship,
    validate_paginated,
)


# ======================================================================
# Shared helpers
# ======================================================================


def _as_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp so instants compare regardless of how
    many fractional digits the server serialised."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ship_epoch_one_then_commit_into_epoch_two() -> dict:
    """One node S1 (zone 4, cutoff minute 1020) with 20 units of a MEDIUM SKU.

    Order O-A101 is committed at 09:00, accepted and fully picked at 09:05,
    packed at 09:30 and tendered at 09:45; the ops-run at 12:00 closes epoch 1
    and opens epoch 2. Order O-A102 is then committed at 12:05 and left at
    ASSIGNED with a 16:05 pick deadline.

    Returns ``store``, ``first_assignment`` and ``second_assignment``.
    """
    net = setup_network(
        node_presets=("S1",),
        sku_presets=("SKU-A",),
        clock="2026-08-03T09:00:00Z",
        stock=[("S1", "SKU-A", 20, 2)],
        packaging=[("S1", "MEDIUM_BOX", 3, 1)],
    )
    store = net["stores"]["S1"]
    sku = net["skus"]["SKU-A"]

    pickup = schedule_pickup(
        store["id"],
        window_start_utc="2026-08-03T09:30:00Z",
        window_end_utc="2026-08-03T11:00:00Z",
        parcel_capacity=2,
    )

    first = setup_order_with_lines(
        [(sku["id"], 2, 4500)],
        order_code="O-A101",
        customer_ref="C-211",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T15:00:00Z",
    )
    commit_routing(first["order"]["id"])
    first_assignment = find_assignment(order_id=first["order"]["id"])

    set_clock("2026-08-03T09:05:00Z")
    accept(first_assignment["id"], store["id"])
    pick_full(first_assignment["id"], store["id"])
    set_clock("2026-08-03T09:30:00Z")
    pack(first_assignment["id"], store["id"], "MEDIUM_BOX")
    set_clock("2026-08-03T09:45:00Z")
    ship(first_assignment["id"], store["id"], pickup["id"])

    set_clock("2026-08-03T12:00:00Z")
    close_windows()

    set_clock("2026-08-03T12:05:00Z")
    second = setup_order_with_lines(
        [(sku["id"], 2, 4500)],
        order_code="O-A102",
        customer_ref="C-212",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T20:00:00Z",
    )
    commit_routing(second["order"]["id"])
    second_assignment = find_assignment(order_id=second["order"]["id"])

    return {
        "store": store,
        "first_assignment": read_assignment(first_assignment["id"]),
        "second_assignment": read_assignment(second_assignment["id"]),
    }


# ======================================================================
# The order-level cost comparison read
# ======================================================================


class TestOrderCostComparisonRead:
    def test_cost_comparison_read_returns_every_field_of_the_provisional_rollup(self):
        """PRD §3.8: "Its body reports the `order_id`, the `variant` used — `FINAL` when the order's `fulfillment_status` is `SHIPPED` and `PROVISIONAL` otherwise — the `parcel_count`, the `component_sum_cents`, the `split_penalty_cents` and `reroute_overhead_cents` actually applied, the `pre_fee_subtotal_cents`, the `network_fee_rate` used and the resulting `network_fee_cents`, the `store_cost_cents`, the `dc_baseline_cost_cents`, the `cost_index_bps` and the `savings_vs_dc_cents`."
        PRD §3.8: "That gap indexes a base shipping charge — 320 cents at a gap of 0, then 380, 445, 520, 610, 700, 800 and 900 cents at gaps of 1 through 7 respectively."
        PRD §3.8: "For each line, the line weight is the served SKU's `unit_weight_grams` multiplied by the units on that line; the number of weight steps is that weight divided by a 500-gram step and rounded up to a whole number of steps; the raw line charge is the zone base charge plus 25 cents per weight step; that raw charge is multiplied by the service multiplier — 1.00 for a `GROUND` order and 1.35 for an `EXPEDITED` one — and the product is rounded half-up to whole cents."
        PRD §3.8: "**Labour cost** is the charged labour minutes multiplied by the node's `labor_rate_cents_per_minute`, rounded up to the next whole cent."
        PRD §3.8: "**Packaging cost** is the base cost of the charged package type — 45 cents for a `POLY_MAILER`, 85 for a `SMALL_BOX`, 130 for a `MEDIUM_BOX` and 190 for a `LARGE_BOX` — plus 15 cents of dunnage per charged unit."
        PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."
        PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."
        PRD §3.8: "Its charged units are `assigned_units`, and its charged package is `derived_package_type`."
        PRD §3.8: "The pre-fee subtotal is that component sum, plus a split penalty of 175 cents for each parcel beyond the first, plus a reroute overhead of 90 cents multiplied by the order's `reroute_attempt_count`."
        PRD §3.8: "The overhead fee rate is then keyed on the pre-fee subtotal: 6.0 percent when the subtotal is strictly below 2000 cents, 4.5 percent when it is strictly below 5000 cents, and 3.0 percent at or above 5000 cents."
        PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
        PRD §3.8: "The distribution-centre baseline is a per-zone handling figure plus a per-unit charge: 1450 cents for `destination_zone` 1, then 1560, 1700, 1850, 2010, 2180, 2360 and 2550 cents for zones 2 through 8, plus 120 cents multiplied by the order's `total_units`."
        PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."
        PRD §3.8: "Savings versus the distribution centre are the baseline minus the store cost, and may of course be negative."
        PRD §3.8: "The **provisional** variant, kept live in `provisional_cost_cents` after every routing change and every assignment status change, includes the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — that is, the five non-terminal statuses plus `SHIPPED` — using each one's `provisional_cost_cents`."
        PRD §3.4: "`projected_cost_cents` is the order-level store cost this run projects, computed on the provisional basis of §3.8 including the split penalty, the reroute overhead and the network overhead fee."
        PRD §3.4: "`projected_dc_cost_cents` is the distribution-centre baseline for the same order at run time."
        PRD §3.4: "`projected_cost_index_bps` is `projected_cost_cents` multiplied by 10000, divided by `projected_dc_cost_cents`, rounded half-up — and 0 when the baseline is 0."

        Design: Corner/calculations/cost_comparison_read_returns_the_full_provisional_rollup
        """
        ctx = setup_committed_assignment(
            node_preset="S1",
            sku_preset="SKU-A",
            on_hand_units=20,
            safety_stock_units=2,
            quantity=2,
            destination_zone=4,
            service_level="GROUND",
            order_code="O-A001",
            customer_ref="C-201",
            promised_ship_by_utc="2026-08-03T15:00:00Z",
            clock="2026-08-03T09:00:00Z",
            with_packaging=False,
            with_pickup=False,
        )
        order_id = ctx["order"]["id"]

        data = cost_comparison(order_id)
        assert_cost_comparison(data)

        assert data["order_id"] == order_id, "the read reports the order it priced"
        assert data["variant"] == "PROVISIONAL", (
            "fulfillment_status is still PENDING, so the variant is PROVISIONAL"
        )
        assert data["parcel_count"] == 1, "one live assignment is one parcel"
        assert data["component_sum_cents"] == 1336, (
            "18 standard minutes * 42 = 756 labour + 160 MEDIUM_BOX packaging + "
            "420 freight (zone gap 0 base 320 + 25 * 4 weight steps) = 1336"
        )
        assert data["split_penalty_cents"] == 0, (
            "no parcel beyond the first, so no split penalty"
        )
        assert data["reroute_overhead_cents"] == 0, (
            "reroute_attempt_count is 0, so no reroute overhead"
        )
        assert data["pre_fee_subtotal_cents"] == 1336, (
            "the pre-fee subtotal is the component sum with no penalty and no overhead"
        )
        assert data["network_fee_rate"] == pytest.approx(0.060, abs=0.0001), (
            "1336 is strictly below 2000, so the fee rate is 6.0 percent"
        )
        assert data["network_fee_cents"] == 80, (
            "1336 * 0.060 = 80.16 rounds half-up to 80"
        )
        assert data["store_cost_cents"] == 1416, "1336 pre-fee plus an 80-cent fee"
        assert data["dc_baseline_cost_cents"] == 2090, (
            "zone-4 handling 1850 plus 120 * 2 units"
        )
        assert data["cost_index_bps"] == 6775, (
            "1416 * 10000 / 2090 = 6775.12 rounds half-up to 6775"
        )
        assert data["savings_vs_dc_cents"] == 674, "2090 baseline minus 1416 store cost"

        order = read_order(order_id)
        assert order["provisional_cost_cents"] == 1416, (
            "the order keeps the same provisional store cost live on the row"
        )
        assert order["dc_baseline_cost_cents"] == 2090, (
            "the order's own baseline matches the comparison read"
        )
        assert order["cost_index_bps"] == 6775, (
            "before final_cost_cents is set, cost_index_bps is read off the "
            "provisional store cost"
        )

        run = read_routing_run(ctx["run"]["id"])
        assert run["projected_cost_cents"] == 1416, (
            "the committing run projected the same order-level store cost"
        )
        assert run["projected_dc_cost_cents"] == 2090, (
            "the run's DC baseline is the order's baseline at run time"
        )
        assert run["projected_cost_index_bps"] == 6775, (
            "1416 * 10000 / 2090 = 6775.12 rounds half-up to 6775"
        )


# ======================================================================
# Performance-window metrics are scoped by the stamped epoch
# ======================================================================


class TestWindowMetricEpochScope:
    def test_window_metrics_read_only_the_assignments_stamped_with_that_epoch(self):
        """PRD §2.10: "Every assignment is stamped at creation with the `epoch` of its node's open window, and that stamp — not the node's current epoch — is what binds the assignment to a window for measurement."
        PRD §3.9: "For every node with an open window, in ascending node `created_at` order, every metric field of that window is computed."
        PRD §3.9: "The window's assignment set is the assignments whose `store_id` is this node and whose stamped `epoch` equals the window's `epoch` — the stamp taken at assignment creation, never the node's current epoch."
        PRD §3.9: "From that set: `assignments_created` is the count of all of them; `assignments_shipped`, `assignments_rejected` and `assignments_cancelled` are the counts at `status` `SHIPPED`, `REJECTED` and `CANCELLED` respectively; `units_promised` is the sum of `assigned_units` over all of them; and `units_shipped` is the sum of `picked_units` over those at `SHIPPED`."
        PRD §3.9: "`fill_rate` is exactly 1.0000 when `units_promised` is 0, and otherwise `units_shipped` divided by `units_promised` rounded half-up to four decimal places."
        PRD §3.9: "`avg_cycle_time_minutes` is exactly 0.00 when `assignments_shipped` is 0, and otherwise the sum of `cycle_time_minutes` over the shipped assignments divided by `assignments_shipped`, rounded half-up to two decimal places."
        PRD §3.9: "`cancellation_rate` is exactly 0.0000 when `assignments_created` is 0, and otherwise `assignments_rejected` plus `assignments_cancelled`, divided by `assignments_created`, rounded half-up to four decimal places."
        PRD §3.9: "`breach_flags` is then built as a subset of three markers appended in this fixed order: `FILL_RATE` when `assignments_shipped` is at least 1 and `fill_rate` is strictly below 0.9000; `CYCLE_TIME` when `assignments_shipped` is at least 1 and `avg_cycle_time_minutes` is strictly greater than four hours; and `CANCELLATION_RATE` when `assignments_created` is at least 1 and `cancellation_rate` is strictly greater than 0.0500."
        PRD §3.9: "`breached` is true exactly when `breach_flags` is non-empty."
        PRD §3.9: "`store_cost_per_order_cents` is 0 when `assignments_shipped` is 0, and otherwise the sum of `final_cost_cents` over the shipped assignments divided by `assignments_shipped`, rounded half-up to whole cents."
        PRD §3.9: "`dc_cost_per_order_cents` is 0 when `assignments_shipped` is 0, and otherwise computed by taking, for each shipped assignment, the distribution-centre base charge for its order's `destination_zone` plus 120 cents multiplied by that assignment's `picked_units`, summing those across the shipped assignments, dividing by `assignments_shipped`, and rounding half-up to whole cents."
        PRD §3.9: "The window's `cost_index_bps` is 0 when `dc_cost_per_order_cents` is 0, and otherwise `store_cost_per_order_cents` multiplied by 10000, divided by `dc_cost_per_order_cents`, rounded half-up."
        PRD §3.9: "`cost_disadvantaged` is true exactly when that index is strictly greater than 11000 basis points."
        PRD §3.9: "`node_action` is `NONE` when `assignments_created` is 0 — an empty window is inert."
        PRD §3.9: "`consecutive_breach_windows` is then set to 0 when the window was non-empty and not breached, incremented by 1 when the window was non-empty and breached, and left completely unchanged when the window was empty — so an empty window never changes posture and never resets the breach counter."
        PRD §3.9: "Every assignment whose `status` is `ASSIGNED` or `ACCEPTED` and whose `pick_deadline_utc` is at or before the current clock instant is cancelled with cancellation reason `PICK_SLA_EXPIRED`, processed in ascending assignment `created_at` order."
        PRD §3.9: "A new performance window at `status` `OPEN` and at the previous `epoch` plus 1 is created for every node whose `node_status` is `ELIGIBLE` or `PROBATION`, with `opened_at_utc` at the clock instant and `closed_at_utc` null."
        PRD §2.3: "Every list response repeats `limit` and `offset` in the envelope's `meta` object alongside `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."

        Design: Corner/calculations/window_metrics_filter_assignments_by_the_epoch_stamped_at_creation
        """
        ctx = _ship_epoch_one_then_commit_into_epoch_two()
        store_id = ctx["store"]["id"]

        assert ctx["first_assignment"]["epoch"] == 1, (
            "the first assignment was stamped with the node's epoch-1 open window"
        )
        assert ctx["second_assignment"]["epoch"] == 2, (
            "the second assignment was stamped with the epoch-2 window opened by "
            "the first ops-run"
        )

        # Second ops-run: it must measure only the epoch-2 window.
        set_clock("2026-08-03T12:30:00Z")
        close_windows()

        response = api_client.list_performance_windows(
            PLANNER, params={"store_id": store_id}
        )
        rows, meta = validate_paginated(response)
        by_epoch = {row["epoch"]: row for row in rows}
        assert meta["total_count"] == 3, (
            "two closed windows plus the freshly opened epoch-3 window"
        )
        assert set(by_epoch) == {1, 2, 3}, (
            f"expected windows at epochs 1, 2 and 3, got {sorted(by_epoch)}"
        )
        assert by_epoch[3]["status"] == "OPEN", (
            "the second close opened the next epoch for this ELIGIBLE node"
        )

        first_window = by_epoch[1]
        assert first_window["assignments_created"] == 1, (
            "the epoch-1 window still counts only its own stamped assignment"
        )
        assert first_window["assignments_shipped"] == 1, (
            "the epoch-1 window keeps its shipped count; a CLOSED window is not "
            "re-aggregated by a later ops-run"
        )
        assert first_window["units_promised"] == 2, (
            "units_promised sums assigned_units over the epoch-1 cohort"
        )
        assert first_window["units_shipped"] == 2, (
            "units_shipped sums picked_units over the epoch-1 shipped assignment"
        )
        assert first_window["fill_rate"] == pytest.approx(1.0000, abs=0.0001), (
            "2 shipped of 2 promised is a fill_rate of 1.0000"
        )
        assert first_window["avg_cycle_time_minutes"] == pytest.approx(45.00, abs=0.01), (
            "the only shipped assignment ran 09:00 to 09:45, so 45.00 minutes"
        )
        assert first_window["store_cost_per_order_cents"] == 1630, (
            "the shipped assignment's final cost was 25 actual minutes * 42 = 1050 "
            "labour + 160 packaging + 420 freight = 1630, over one shipped parcel"
        )

        second_window = by_epoch[2]
        assert second_window["assignments_created"] == 1, (
            "only the assignment stamped epoch 2 belongs to the epoch-2 window"
        )
        assert second_window["assignments_shipped"] == 0, (
            "the epoch-2 assignment never shipped"
        )
        assert second_window["assignments_rejected"] == 0, (
            "nothing was rejected inside epoch 2"
        )
        assert second_window["assignments_cancelled"] == 0, (
            "nothing was cancelled inside epoch 2"
        )
        assert second_window["units_promised"] == 2, (
            "the epoch-2 cohort promised 2 units"
        )
        assert second_window["units_shipped"] == 0, (
            "no picked units shipped inside epoch 2"
        )
        assert second_window["fill_rate"] == pytest.approx(0.0000, abs=0.0001), (
            "units_promised is 2, so fill_rate is 0/2 = 0.0000 and not the "
            "1.0000 reserved for a zero-promise window"
        )
        assert second_window["breach_flags"] == [], (
            "the FILL_RATE flag needs assignments_shipped >= 1, so a 0.0000 "
            "fill_rate on an unshipped window raises no flag"
        )
        assert second_window["breached"] is False, (
            "breached is true exactly when breach_flags is non-empty"
        )
        assert second_window["avg_cycle_time_minutes"] == pytest.approx(0.00, abs=0.01), (
            "assignments_shipped is 0, so avg_cycle_time_minutes is exactly 0.00"
        )
        assert second_window["cancellation_rate"] == pytest.approx(0.0000, abs=0.0001), (
            "0 rejected plus 0 cancelled over 1 created is 0.0000"
        )
        assert second_window["store_cost_per_order_cents"] == 0, (
            "assignments_shipped is 0, so store_cost_per_order_cents is 0"
        )
        assert second_window["dc_cost_per_order_cents"] == 0, (
            "assignments_shipped is 0, so dc_cost_per_order_cents is 0"
        )
        assert second_window["cost_index_bps"] == 0, (
            "dc_cost_per_order_cents is 0, so the window's cost index is 0"
        )
        assert second_window["cost_disadvantaged"] is False, (
            "a 0-basis-point index is not strictly greater than 11000"
        )
        assert second_window["node_action"] == "NONE", (
            "a non-empty, unbreached window at an ELIGIBLE node takes no action"
        )

        assert read_assignment(ctx["second_assignment"]["id"])["status"] == "ASSIGNED", (
            "the 12:30 ops-run reaps only assignments at or past their pick "
            "deadline, and this one runs to 16:05"
        )

        store = read_store(store_id)
        assert store["consecutive_breach_windows"] == 0, (
            "a non-empty, unbreached window resets the breach counter to 0"
        )
        assert store["node_status"] == "ELIGIBLE", (
            "no breach means no posture change"
        )


# ======================================================================
# The billable-labour floor on the final variant
# ======================================================================


class TestMinBillableLaborFloor:
    def test_seven_minutes_of_actual_labour_is_billed_at_the_ten_minute_floor(self):
        """PRD §3.5: "On success `packed_at` is set to the clock instant, `package_type` is stored, and `labor_minutes_actual` is computed as the elapsed time from `accepted_at` to `packed_at` expressed in whole minutes with any remaining seconds discarded."
        PRD §3.8: "The **final** variant, written to `final_cost_cents` at ship, charges *actual* clocked labour: the greater of `labor_minutes_actual` and a 10-minute billable minimum, where `labor_minutes_actual` is the whole minutes from `accepted_at` to `packed_at` with remaining seconds discarded."
        PRD §3.8: "Its charged units are `picked_units`, and its charged package is the `package_type` the associate actually recorded at pack."
        PRD §3.8: "**Labour cost** is the charged labour minutes multiplied by the node's `labor_rate_cents_per_minute`, rounded up to the next whole cent."
        PRD §3.8: "**Packaging cost** is the base cost of the charged package type — 45 cents for a `POLY_MAILER`, 85 for a `SMALL_BOX`, 130 for a `MEDIUM_BOX` and 190 for a `LARGE_BOX` — plus 15 cents of dunnage per charged unit."
        PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."
        PRD §3.8: "The **final** variant, written to `final_cost_cents` when `fulfillment_status` becomes `SHIPPED`, includes only assignments at `status` `SHIPPED`, using each one's `final_cost_cents`; because the component sum changes, the fee tier can land in a different band than the provisional pass did, which is exactly what `cost_variance_cents` — `final_cost_cents` minus `provisional_cost_cents` — is there to expose."
        PRD §3.8: "The overhead fee rate is then keyed on the pre-fee subtotal: 6.0 percent when the subtotal is strictly below 2000 cents, 4.5 percent when it is strictly below 5000 cents, and 3.0 percent at or above 5000 cents."
        PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
        PRD §3.8: "The order's `cost_index_bps` uses `final_cost_cents` once that is set and `provisional_cost_cents` before then."
        PRD §3.8: "Savings versus the distribution centre are the baseline minus the store cost, and may of course be negative."
        PRD §3.6: "The assignment's `status` becomes `SHIPPED`, `shipped_at` is set to the clock instant, `carrier_pickup_id` is stored, and `cycle_time_minutes` is computed as the elapsed time from `created_at` to `shipped_at` in whole minutes with remaining seconds discarded."
        PRD §3.6: "From `PENDING`, a ship that leaves `shipped_units` above 0 with that same sum exactly equal to `total_units` moves the order straight to `SHIPPED`, writing `final_cost_cents` on the final variant, setting `cost_variance_cents` to `final_cost_cents` minus `provisional_cost_cents`, and recomputing `cost_index_bps` against the final figure."

        Design: Corner/calculations/min_billable_labor_floor_replaces_a_seven_minute_actual
        """
        ctx = setup_shipped_assignment(
            node_preset="S1",
            sku_preset="SKU-A",
            on_hand_units=20,
            safety_stock_units=2,
            quantity=2,
            destination_zone=4,
            service_level="GROUND",
            order_code="O-A201",
            customer_ref="C-221",
            promised_ship_by_utc="2026-08-03T15:00:00Z",
            clock="2026-08-03T09:00:00Z",
            packaging_on_hand=2,
            pickup_start="2026-08-03T09:10:00Z",
            pickup_end="2026-08-03T11:00:00Z",
            parcel_capacity=2,
            accept_at="2026-08-03T09:05:00Z",
            pick_at="2026-08-03T09:06:00Z",
            pack_at="2026-08-03T09:12:00Z",
            ship_at="2026-08-03T09:15:00Z",
            package_type_on_pack="MEDIUM_BOX",
        )
        assignment = read_assignment(ctx["assignment"]["id"])

        assert assignment["labor_minutes_actual"] == 7, (
            "accepted 09:05 and packed 09:12 is 7 whole minutes; the stored "
            "actual is never floored"
        )
        assert assignment["final_cost_cents"] == 1000, (
            "billable minutes are max(7, 10) = 10, so 10 * 42 = 420 labour + 160 "
            "MEDIUM_BOX packaging + 420 freight = 1000, not the 874 a raw "
            "7-minute billing would produce"
        )
        assert assignment["cycle_time_minutes"] == 15, (
            "created 09:00 and shipped 09:15 is 15 whole minutes"
        )

        order = read_order(ctx["order"]["id"])
        assert order["fulfillment_status"] == "SHIPPED", (
            "every unit of the order resolved on this tender"
        )
        assert order["provisional_cost_cents"] == 1416, (
            "the provisional pass charges the 18-minute labour standard: 1336 "
            "pre-fee plus an 80-cent fee"
        )
        assert order["final_cost_cents"] == 1060, (
            "the final pass charges 1000 pre-fee at 6.0 percent, a 60-cent fee, "
            "so 1060 and never the 927 a raw 7-minute billing would produce"
        )
        assert order["cost_variance_cents"] == -356, (
            "1060 final minus 1416 provisional is a negative variance of -356"
        )
        assert order["cost_index_bps"] == 5072, (
            "1060 * 10000 / 2090 = 5071.77 rounds half-up to 5072"
        )

        comparison = cost_comparison(ctx["order"]["id"])
        assert_cost_comparison(comparison)
        assert comparison["variant"] == "FINAL", (
            "fulfillment_status is SHIPPED, so the read uses the FINAL variant"
        )
        assert comparison["component_sum_cents"] == 1000, (
            "the final component sum is the shipped assignment's final cost"
        )
        assert comparison["store_cost_cents"] == 1060, (
            "1000 pre-fee plus the 60-cent network fee"
        )
        assert comparison["savings_vs_dc_cents"] == 1030, (
            "2090 baseline minus 1060 store cost"
        )


# ======================================================================
# Half-cent network fees round half-up on both passes
# ======================================================================


class TestHalfCentFeeRounding:
    def test_both_the_provisional_and_the_final_network_fee_round_a_half_cent_up(self):
        """PRD §2.7: "Wherever a monetary result would be fractional, it is rounded to a whole number of cents using the round-half-up convention, meaning a value exactly at the halfway point rounds away from zero."
        PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
        PRD §3.8: "The overhead fee rate is then keyed on the pre-fee subtotal: 6.0 percent when the subtotal is strictly below 2000 cents, 4.5 percent when it is strictly below 5000 cents, and 3.0 percent at or above 5000 cents."
        PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."
        PRD §3.8: "The **final** variant, written to `final_cost_cents` at ship, charges *actual* clocked labour: the greater of `labor_minutes_actual` and a 10-minute billable minimum, where `labor_minutes_actual` is the whole minutes from `accepted_at` to `packed_at` with remaining seconds discarded."
        PRD §3.8: "For each line, the line weight is the served SKU's `unit_weight_grams` multiplied by the units on that line; the number of weight steps is that weight divided by a 500-gram step and rounded up to a whole number of steps; the raw line charge is the zone base charge plus 25 cents per weight step; that raw charge is multiplied by the service multiplier — 1.00 for a `GROUND` order and 1.35 for an `EXPEDITED` one — and the product is rounded half-up to whole cents."
        PRD §3.8: "That gap indexes a base shipping charge — 320 cents at a gap of 0, then 380, 445, 520, 610, 700, 800 and 900 cents at gaps of 1 through 7 respectively."
        PRD §3.8: "The distribution-centre baseline is a per-zone handling figure plus a per-unit charge: 1450 cents for `destination_zone` 1, then 1560, 1700, 1850, 2010, 2180, 2360 and 2550 cents for zones 2 through 8, plus 120 cents multiplied by the order's `total_units`."
        PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."
        PRD §3.5: "On success `packed_at` is set to the clock instant, `package_type` is stored, and `labor_minutes_actual` is computed as the elapsed time from `accepted_at` to `packed_at` expressed in whole minutes with any remaining seconds discarded."
        PRD §3.6: "From `PENDING`, a ship that leaves `shipped_units` above 0 with that same sum exactly equal to `total_units` moves the order straight to `SHIPPED`, writing `final_cost_cents` on the final variant, setting `cost_variance_cents` to `final_cost_cents` minus `provisional_cost_cents`, and recomputing `cost_index_bps` against the final figure."

        Design: Corner/calculations/two_half_cent_fees_in_one_order_both_round_half_up
        """
        ctx = setup_committed_assignment(
            node_preset="S5",
            sku_preset="SKU-A",
            on_hand_units=10,
            safety_stock_units=2,
            quantity=1,
            destination_zone=4,
            service_level="GROUND",
            order_code="O-A301",
            customer_ref="C-231",
            promised_ship_by_utc="2026-08-03T15:00:00Z",
            clock="2026-08-03T09:00:00Z",
            package_type="MEDIUM_BOX",
            packaging_on_hand=2,
            pickup_start="2026-08-03T09:10:00Z",
            pickup_end="2026-08-03T11:00:00Z",
            parcel_capacity=2,
        )
        store_id = ctx["store"]["id"]
        assignment_id = ctx["assignment"]["id"]
        order_id = ctx["order"]["id"]

        # --- the provisional pass: 875 * 0.060 lands on exactly 52.5 cents
        provisional = cost_comparison(order_id)
        assert_cost_comparison(provisional)
        assert provisional["variant"] == "PROVISIONAL", (
            "nothing has shipped yet, so the read uses the PROVISIONAL variant"
        )
        assert read_assignment(assignment_id)["provisional_cost_cents"] == 875, (
            "12 standard minutes * 25 = 300 labour + 145 MEDIUM_BOX packaging + "
            "430 freight (zone gap 1 base 380 + 25 * 2 weight steps) = 875"
        )
        assert provisional["component_sum_cents"] == 875, (
            "the single live assignment contributes its provisional cost"
        )
        assert provisional["network_fee_cents"] == 53, (
            "875 * 0.060 = 52.5 exactly, which rounds half-up to 53 and never "
            "down to the 52 a banker's or truncating rule would give"
        )
        assert provisional["store_cost_cents"] == 928, (
            "875 pre-fee plus the 53-cent fee"
        )
        assert provisional["dc_baseline_cost_cents"] == 1970, (
            "zone-4 handling 1850 plus 120 * 1 unit"
        )
        assert provisional["cost_index_bps"] == 4711, (
            "928 * 10000 / 1970 = 4710.66 rounds half-up to 4711"
        )

        # --- drive the parcel to a tender: 20 actual minutes of labour
        set_clock("2026-08-03T09:05:00Z")
        accept(assignment_id, store_id)
        set_clock("2026-08-03T09:06:00Z")
        pick_full(assignment_id, store_id)
        set_clock("2026-08-03T09:25:00Z")
        pack(assignment_id, store_id, "MEDIUM_BOX")
        set_clock("2026-08-03T09:30:00Z")
        ship(assignment_id, store_id, ctx["pickup"]["id"])

        assignment = read_assignment(assignment_id)
        assert assignment["labor_minutes_actual"] == 20, (
            "labour is clocked from accepted_at 09:05 to packed_at 09:25, so 20 "
            "minutes, and not the 19 that measuring from picked_at 09:06 gives"
        )
        assert assignment["final_cost_cents"] == 1075, (
            "20 billable minutes * 25 = 500 labour + 145 packaging + 430 freight"
        )

        # --- the final pass: 1075 * 0.060 lands on exactly 64.5 cents
        final = cost_comparison(order_id)
        assert_cost_comparison(final)
        assert final["variant"] == "FINAL", (
            "the order is fully shipped, so the read uses the FINAL variant"
        )
        assert final["component_sum_cents"] == 1075, (
            "the final component sum is the shipped assignment's final cost"
        )
        assert final["network_fee_cents"] == 65, (
            "1075 * 0.060 = 64.5 exactly, which rounds half-up to 65 and never "
            "down to 64"
        )

        order = read_order(order_id)
        assert order["final_cost_cents"] == 1140, (
            "1075 pre-fee plus the 65-cent fee; a rule that rounded 64.5 down "
            "would report 1139"
        )
        assert order["cost_variance_cents"] == 212, (
            "1140 final minus 928 provisional"
        )
        assert order["cost_index_bps"] == 5787, (
            "1140 * 10000 / 1970 = 5786.80 rounds half-up to 5787, not the 5782 "
            "that two down-rounded fees would give"
        )


# ======================================================================
# The pick deadline is a minimum of two instants
# ======================================================================


class TestPickDeadlineClamp:
    def test_pick_deadline_takes_the_cutoff_instant_when_it_precedes_the_sla(self):
        """PRD §3.5: "And `pick_deadline_utc` is the earlier of two instants: four hours after the assignment's `created_at`, and the instant on the creation date's UTC calendar day that falls `cutoff_utc_minutes` minutes after midnight UTC."
        PRD §2.6: "Each node publishes a same-day cutoff as `cutoff_utc_minutes`, an integer from 0 to 1439 inclusive counting minutes after midnight UTC."
        PRD §3.5: "Its `status` begins at `ASSIGNED` and ends at one of the three terminal states `SHIPPED`, `REJECTED` or `CANCELLED`."
        PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."
        PRD §3.8: "That gap indexes a base shipping charge — 320 cents at a gap of 0, then 380, 445, 520, 610, 700, 800 and 900 cents at gaps of 1 through 7 respectively."
        PRD §3.8: "For each line, the line weight is the served SKU's `unit_weight_grams` multiplied by the units on that line; the number of weight steps is that weight divided by a 500-gram step and rounded up to a whole number of steps; the raw line charge is the zone base charge plus 25 cents per weight step; that raw charge is multiplied by the service multiplier — 1.00 for a `GROUND` order and 1.35 for an `EXPEDITED` one — and the product is rounded half-up to whole cents."
        PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
        PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."

        Design: Corner/calculations/pick_deadline_is_clamped_by_the_cutoff_instant_not_the_sla
        """
        ctx = setup_committed_assignment(
            node_preset="S3",
            sku_preset="SKU-A",
            on_hand_units=20,
            safety_stock_units=2,
            quantity=2,
            destination_zone=4,
            service_level="GROUND",
            order_code="O-A401",
            customer_ref="C-241",
            promised_ship_by_utc="2026-08-03T20:00:00Z",
            clock="2026-08-03T14:00:00Z",
            with_packaging=False,
            with_pickup=False,
        )
        assignment = read_assignment(ctx["assignment"]["id"])

        deadline = _as_instant(assignment["pick_deadline_utc"])
        assert deadline == _as_instant("2026-08-03T16:00:00Z"), (
            "a 14:00 commit at a node whose cutoff minute is 960 clamps the "
            "deadline to the 16:00Z cutoff instant, earlier than the four-hour "
            f"SLA instant 18:00Z; got {assignment['pick_deadline_utc']}"
        )
        assert deadline != _as_instant("2026-08-03T18:00:00Z"), (
            "the four-hour SLA reading 18:00Z must not survive the clamp"
        )
        assert assignment["status"] == "ASSIGNED", (
            "a freshly committed assignment starts at ASSIGNED"
        )
        assert assignment["provisional_cost_cents"] == 985, (
            "14 standard minutes * 20 = 280 labour + 160 MEDIUM_BOX packaging + "
            "545 freight (zone gap 2 base 445 + 25 * 4 weight steps) = 985"
        )

        order = read_order(ctx["order"]["id"])
        assert order["provisional_cost_cents"] == 1044, (
            "985 pre-fee at 6.0 percent is a 59-cent fee, so 1044"
        )
        assert order["cost_index_bps"] == 4995, (
            "1044 * 10000 / 2090 = 4995.22 rounds half-up to 4995"
        )


# ======================================================================
# The weighted routing score
# ======================================================================


class TestRoutingScoreWeights:
    def test_routing_score_sums_the_four_weighted_factors_without_a_penalty(self):
        """PRD §3.3: "The score is the sum of three components, each rounded half-up to four decimal places, with the sum then rounded half-up to two decimal places."
        PRD §3.3: "The **capacity component** starts from capacity headroom: the larger of 0 and `daily_unit_capacity` minus `units_committed_epoch`. That headroom is divided by a reference of 200 units, the quotient is capped at 1, and the result is multiplied by a weight of 40."
        PRD §3.3: "The **labour component** starts from labour headroom: the larger of 0 and `staffed_labor_minutes` minus `reserved_labor_minutes`. That headroom is divided by a reference of eight staffed hours, the quotient is capped at 1, and the result is multiplied by a weight of 30."
        PRD §3.3: "The **performance component** is a weight of 30 multiplied by a performance ratio between 0 and 1."
        PRD §3.3: "A node with zero closed performance windows uses a flat performance ratio of 0.60 and records `eligibility_score_basis` as `COLD_START`."
        PRD §3.4: "Its `coverage_units` is the smallest of four numbers: its promise-able units, its capacity units left, its labour units left, and the total remaining demand."
        PRD §3.4: "`coverage_ratio` is `coverage_units` divided by the total remaining demand, rounded half-up to four decimal places."
        PRD §3.4: "`cost_estimate_cents` is the provisional fulfillment cost of exactly that planned allocation at that node, computed as in §3.8."
        PRD §3.4: "`delivery_days` is the transit time from this node to the order's destination, read from the zone-gap table: a gap of 0 gives 1 day, a gap of 1 or 2 gives 2 days, a gap of 3 gives 3 days, a gap of 4 gives 4 days, a gap of 5 or 6 gives 5 days, and a gap of 7 gives 6 days, where the gap is the absolute difference between the order's `destination_zone` and the node's `origin_zone`; on an `EXPEDITED` order that figure is reduced by one day but never below the one-day minimum."
        PRD §3.4: "`routing_score` is a weighted blend of four factors, each rounded half-up to four decimal places."
        PRD §3.4: "The coverage factor is simply `coverage_ratio`."
        PRD §3.4: "The cost factor takes a ceiling of 2000 cents minus `cost_estimate_cents`, divides by the 1600-cent span between that ceiling and a floor of 400 cents, and clamps the result into 0 to 1 inclusive."
        PRD §3.4: "The speed factor takes a maximum of 6 transit days minus `delivery_days`, divides by the 5-day span between that maximum and a minimum of 1 day, and clamps into 0 to 1 inclusive."
        PRD §3.4: "The health factor is the node's `eligibility_score` divided by 100."
        PRD §3.4: "Those factors are weighted 45 for coverage, 25 for cost, 20 for speed and 10 for health and summed; a node whose `node_status` is `PROBATION` then has a penalty of 8 points subtracted; and the result is rounded half-up to two decimal places."
        PRD §3.4: "Eligible candidates in the iteration are ranked by `routing_score` descending, then by `cost_estimate_cents` ascending, then by `coverage_units` descending, then by node `created_at` ascending — never by node `id` — and each is given its 1-based `rank` within the iteration."
        PRD §3.4: "A `PROVISIONAL` run persists candidate rows and the run's projections with `status` `EVALUATED`; it creates no assignment, moves no reservation, emits no notification, and reports the cost guardrail without ever being blocked by it."
        PRD §3.4: "`projected_cost_cents` is the order-level store cost this run projects, computed on the provisional basis of §3.8 including the split penalty, the reroute overhead and the network overhead fee."
        PRD §3.4: "`projected_cost_index_bps` is `projected_cost_cents` multiplied by 10000, divided by `projected_dc_cost_cents`, rounded half-up — and 0 when the baseline is 0."
        PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."
        PRD §2.9: "At the order level, `total_units` equals the sum of every demand line's `quantity`, and `unassigned_units` equals the sum of every demand line's `open_units`."

        Design: Corner/calculations/routing_score_weights_coverage_cost_speed_and_node_health
        """
        net = setup_network(
            node_presets=("S5",),
            sku_presets=("SKU-A",),
            clock="2026-08-03T09:00:00Z",
            stock=[("S5", "SKU-A", 10, 2)],
        )
        store = net["stores"]["S5"]
        sku = net["skus"]["SKU-A"]

        built = setup_order_with_lines(
            [(sku["id"], 1, 4500)],
            order_code="O-A501",
            customer_ref="C-251",
            destination_zone=4,
            service_level="GROUND",
            promised_ship_by_utc="2026-08-03T15:00:00Z",
        )
        order_id = built["order"]["id"]

        run = provisional_routing(order_id)

        node = read_store(store["id"])
        assert node["eligibility_score"] == pytest.approx(63.00, abs=0.01), (
            "capacity 40 * 100/200 = 20.0000, labour 30 * 400/480 = 25.0000 and a "
            "cold-start performance 30 * 0.60 = 18.0000 sum to 63.00"
        )
        assert node["eligibility_score_basis"] == "COLD_START", (
            "the node has no closed performance window yet"
        )

        candidates = find_routing_candidates(routing_run_id=run["id"])
        assert len(candidates) == 1, (
            f"the only node in the network is evaluated once, got {len(candidates)}"
        )
        candidate = candidates[0]

        assert candidate["eligible"] is True, (
            "the node clears every eligibility clause"
        )
        assert candidate["ineligible_reason"] is None, (
            "no clause failed, so no reason is recorded"
        )
        assert candidate["coverage_units"] == 1, (
            "the smallest of promise-able 8, capacity 100, labour 195 and the "
            "1-unit remaining demand"
        )
        assert candidate["coverage_ratio"] == pytest.approx(1.0000, abs=0.0001), (
            "1 covered unit over 1 unit of remaining demand"
        )
        assert candidate["cost_estimate_cents"] == 875, (
            "12 standard minutes * 25 = 300 labour + 145 MEDIUM_BOX packaging + "
            "430 freight (zone gap 1 base 380 + 25 * 2 weight steps) = 875"
        )
        assert candidate["delivery_days"] == 2, (
            "a zone gap of 1 on a GROUND order gives 2 transit days"
        )
        assert candidate["routing_score"] == pytest.approx(84.88, abs=0.01), (
            "45 * 1.0000 coverage + 25 * 0.7031 cost ((2000-875)/1600) + 20 * "
            "0.8000 speed ((6-2)/5) + 10 * 0.6300 health (63.00/100) = 84.8775, "
            "which rounds half-up to 84.88 with no probation penalty"
        )
        assert candidate["rank"] == 1, (
            "the only eligible candidate takes rank 1 in its iteration"
        )

        run = read_routing_run(run["id"])
        assert run["mode"] == "PROVISIONAL", "the run was started in PROVISIONAL mode"
        assert run["status"] == "EVALUATED", (
            "a PROVISIONAL run records its projections with status EVALUATED"
        )
        assert run["projected_cost_cents"] == 928, (
            "875 pre-fee at 6.0 percent is a 53-cent fee, so 928"
        )
        assert run["projected_dc_cost_cents"] == 1970, (
            "zone-4 handling 1850 plus 120 * 1 unit"
        )
        assert run["projected_cost_index_bps"] == 4711, (
            "928 * 10000 / 1970 = 4710.66 rounds half-up to 4711"
        )

        order = read_order(order_id)
        assert order["routing_status"] == "UNROUTABLE", (
            "a routing run now exists but the PROVISIONAL run created no "
            "assignment, so covered units is 0"
        )
        assert order["unassigned_units"] == 1, (
            "the PROVISIONAL run moved no reservation, so the unit stays open"
        )
