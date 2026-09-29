"""Threshold boundaries: every gate is probed at the value the PRD declares
inclusive and again one step past it.

Each test builds its own network, order and assignment state because the
database is empty when the test starts.
"""

import pytest

from test_helpers import (
    PLANNER,
    accept,
    adjust_inventory,
    close_windows,
    commit_routing,
    find_assignment,
    find_assignments,
    find_routing_candidates,
    make_store_associate_headers,
    order_version,
    pack,
    pick_full,
    read_assignment,
    read_inventory,
    read_order,
    read_order_line,
    read_packaging,
    read_store,
    set_clock,
    setup_network,
    setup_order_with_lines,
    setup_picked_assignment,
    setup_shipped_assignment,
    validate_error,
    validate_success,
)

CLOCK_START = "2026-08-03T09:00:00Z"


# ======================================================================
# Shared preambles
# ======================================================================


def _assert_instant(value, expected_prefix: str, field: str) -> None:
    """A clock-stamped instant must carry the second it was taken at."""
    assert value is not None, f"{field} must be stamped with the clock instant"
    assert value.startswith(expected_prefix), (
        f"{field} should be the clock instant {expected_prefix}Z, got {value}"
    )


def _setup_single_node_order(on_hand_units: int, safety_stock_units: int) -> dict:
    """One node, one SKU stocked at the given buffer, one unrouted 1-unit order."""
    net = setup_network(
        node_presets=("S1",),
        sku_presets=("SKU-A",),
        clock=CLOCK_START,
        stock=[("S1", "SKU-A", on_hand_units, safety_stock_units)],
    )
    store = net["stores"]["S1"]
    sku = net["skus"]["SKU-A"]
    built = setup_order_with_lines(
        [(sku["id"], 1, 4500)],
        order_code="O-5401",
        customer_ref="C-18",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T16:00:00Z",
    )
    return {
        "store": store,
        "sku": sku,
        "inventory": net["inventories"][("S1", "SKU-A")],
        "order": built["order"],
        "line": built["lines"][0],
    }


def _setup_picked_assignment_at_cutoff_node() -> dict:
    """A node whose cutoff_utc_minutes is 1020 (17:00 UTC) holding one PICKED
    assignment accepted at 09:05."""
    return setup_picked_assignment(
        node_preset="S1",
        sku_preset="SKU-A",
        quantity=2,
        on_hand_units=12,
        safety_stock_units=2,
        packaging_on_hand=5,
        with_pickup=False,
        clock=CLOCK_START,
        accept_at="2026-08-03T09:05:00Z",
        pick_at="2026-08-03T09:10:00Z",
        order_code="O-5501",
        customer_ref="C-19",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T23:00:00Z",
    )


def _close_epoch_with_one_shipped_and_one_open(
    shipped_quantity: int, still_assigned_quantity: int
) -> dict:
    """One node ships ``shipped_quantity`` units in full, then takes a second
    order of ``still_assigned_quantity`` units that stays ASSIGNED, then the
    operations run closes the epoch."""
    ctx = setup_shipped_assignment(
        node_preset="S1",
        sku_preset="SKU-A",
        quantity=shipped_quantity,
        on_hand_units=20,
        safety_stock_units=2,
        packaging_on_hand=5,
        clock=CLOCK_START,
        accept_at="2026-08-03T09:05:00Z",
        pick_at="2026-08-03T09:10:00Z",
        pack_at="2026-08-03T09:20:00Z",
        ship_at="2026-08-03T09:30:00Z",
        order_code="O-5601",
        customer_ref="C-21",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T16:00:00Z",
        pickup_start="2026-08-03T09:00:00Z",
        pickup_end="2026-08-03T12:00:00Z",
    )
    store = ctx["store"]

    set_clock("2026-08-03T09:35:00Z")
    second = setup_order_with_lines(
        [(ctx["sku"]["id"], still_assigned_quantity, 4500)],
        order_code="O-5602",
        customer_ref="C-22",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T16:00:00Z",
    )
    commit_routing(second["order"]["id"])
    open_assignment = find_assignment(
        order_id=second["order"]["id"], store_id=store["id"]
    )

    set_clock("2026-08-03T09:40:00Z")
    closed = close_windows()

    return {
        "store": read_store(store["id"]),
        "shipped_assignment": read_assignment(ctx["assignment"]["id"]),
        "open_assignment": open_assignment,
        "closed_windows": closed,
    }


def _setup_kiosk_with_three_assignments() -> dict:
    """A thinly staffed node (staffed_labor_minutes 60) holding three ASSIGNED
    assignments of 2, 4 and 1 units, with the clock at 09:05."""
    net = setup_network(
        node_presets=("S4",),
        sku_presets=("SKU-A",),
        clock=CLOCK_START,
        stock=[("S4", "SKU-A", 20, 2)],
        packaging=[("S4", "MEDIUM_BOX", 5, 1)],
    )
    store = net["stores"]["S4"]
    sku = net["skus"]["SKU-A"]

    assignments = []
    for order_code, customer_ref, quantity in (
        ("O-5701", "C-25", 2),
        ("O-5702", "C-26", 4),
        ("O-5703", "C-27", 1),
    ):
        built = setup_order_with_lines(
            [(sku["id"], quantity, 4500)],
            order_code=order_code,
            customer_ref=customer_ref,
            destination_zone=4,
            service_level="GROUND",
            promised_ship_by_utc="2026-08-03T16:00:00Z",
        )
        commit_routing(built["order"]["id"])
        assignments.append(
            find_assignment(order_id=built["order"]["id"], store_id=store["id"])
        )

    set_clock("2026-08-03T09:05:00Z")
    return {
        "store": store,
        "sku": sku,
        "supply": net["supplies"][("S4", "MEDIUM_BOX")],
        "assignments": assignments,
    }


# ======================================================================
# available_to_promise_units at exactly 0 versus exactly 1
# ======================================================================


class TestAvailableToPromiseBoundary:
    def test_routing_run_finds_no_eligible_node_when_available_to_promise_is_exactly_zero(
        self, api
    ):
        """PRD §3.1: "Creation sets `reserved_units` to 0, leaves `last_adjustment_reason` null, and derives `available_to_promise_units` as the larger of 0 and the result of taking `on_hand_units`, subtracting `reserved_units`, then subtracting `safety_stock_units`."
        PRD §3.4: "Eight eligibility clauses are tested in this pinned order, and the first one that fails both marks the candidate as not `eligible` and records the reason in `ineligible_reason`:"
        PRD §3.4: "the node's promise-able units, being the sum over the SKUs still in remaining demand of the smaller of that SKU's remaining demand and that node's `available_to_promise_units` for it (treated as 0 when the node stocks no row for the SKU), is at least 1 — otherwise `NO_ATP`."
        PRD §3.4: "If the pool was already empty on the very first iteration, the run's `status` becomes `NO_ELIGIBLE_NODE` with `selected_store_count` 0 and `unfulfillable_units` equal to the order's `unassigned_units`, a notification of type `UNROUTABLE` is emitted, and no assignment and no reservation change occurs at all."
        PRD §3.4: "`candidate_count` records how many candidate rows this run persisted across all iterations."
        PRD §3.4: "Candidates that failed the eligibility filter carry a null `routing_score` and a null `rank`; they are still persisted so the planner can see why they lost."

        on_hand 5 with a safety buffer of 5 leaves available_to_promise_units at
        exactly 0, one unit short of the clause's "at least 1".

        Design: Difficulty/boundary_precision_check/routing_run_flips_at_available_to_promise_exactly_zero
        """
        ctx = _setup_single_node_order(on_hand_units=5, safety_stock_units=5)
        before = read_inventory(ctx["inventory"]["id"])
        assert before["available_to_promise_units"] == 0, (
            "on_hand 5 minus reserved 0 minus safety 5 is exactly 0 promise-able units"
        )

        run = validate_success(
            api.create_routing_run(
                ctx["order"]["id"],
                {
                    "mode": "COMMIT",
                    "expected_order_version": order_version(ctx["order"]["id"]),
                },
                PLANNER,
            ),
            201,
        )

        assert run["status"] == "NO_ELIGIBLE_NODE", (
            "an empty candidate pool on the first iteration makes the run "
            f"NO_ELIGIBLE_NODE, got {run['status']}"
        )
        assert run["candidate_count"] == 1, (
            "the single node is still evaluated and persisted as one candidate row"
        )
        assert run["selected_store_count"] == 0, (
            "no node may be selected when the pool is empty"
        )
        assert run["unfulfillable_units"] == 1, (
            "the order's one unassigned unit is unfulfillable"
        )

        candidates = find_routing_candidates(routing_run_id=run["id"])
        assert len(candidates) == 1, f"expected exactly one candidate, got {len(candidates)}"
        candidate = candidates[0]
        assert candidate["iteration"] == 1, "the only evaluation happened in iteration 1"
        assert candidate["eligible"] is False, (
            "a node with 0 promise-able units fails the eighth eligibility clause"
        )
        assert candidate["ineligible_reason"] == "NO_ATP", (
            f"ineligible_reason must be NO_ATP, got {candidate['ineligible_reason']}"
        )
        assert candidate["coverage_units"] == 0, "an ineligible node covers nothing"
        assert candidate["routing_score"] is None, (
            "a candidate that failed the eligibility filter carries a null routing_score"
        )
        assert candidate["rank"] is None, (
            "a candidate that failed the eligibility filter carries a null rank"
        )
        assert candidate["selected"] is False, "an ineligible candidate is never selected"

        assert find_assignments(order_id=ctx["order"]["id"]) == [], (
            "no assignment may be created when the pool is empty on the first iteration"
        )
        after = read_inventory(ctx["inventory"]["id"])
        assert after["reserved_units"] == 0, (
            "no reservation change occurs at all on a NO_ELIGIBLE_NODE run"
        )
        assert after["available_to_promise_units"] == 0, (
            "available_to_promise_units stays at exactly 0"
        )

    def test_routing_run_commits_when_available_to_promise_is_exactly_one(self, api):
        """PRD §3.1: "An adjustment carries `expected_inventory_version`, a `counted_on_hand_units` figure, a `reason` of `CYCLE_COUNT`, `SHRINK`, `RECEIPT` or `MARKDOWN_PULL`, and optionally a replacement `safety_stock_units`."
        PRD §3.1: "On success `on_hand_units` is overwritten with `counted_on_hand_units`, `last_adjustment_reason` records the supplied `reason`, `available_to_promise_units` is recomputed, the node's `eligibility_score` is recomputed, and the row's `version` increments."
        PRD §3.1: "Creation sets `reserved_units` to 0, leaves `last_adjustment_reason` null, and derives `available_to_promise_units` as the larger of 0 and the result of taking `on_hand_units`, subtracting `reserved_units`, then subtracting `safety_stock_units`."
        PRD §3.1: "A row's `reserved_units` is always the sum, over the assignment lines whose owning assignment belongs to this node and whose served demand line references this SKU, of that line's `units_assigned` minus its `units_cancelled`, counting only assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."
        PRD §3.4: "the node's promise-able units, being the sum over the SKUs still in remaining demand of the smaller of that SKU's remaining demand and that node's `available_to_promise_units` for it (treated as 0 when the node stocks no row for the SKU), is at least 1 — otherwise `NO_ATP`."
        PRD §3.4: "Its `coverage_units` is the smallest of four numbers: its promise-able units, its capacity units left, its labour units left, and the total remaining demand."
        PRD §3.4: "`coverage_ratio` is `coverage_units` divided by the total remaining demand, rounded half-up to four decimal places."
        PRD §3.4: "Eligible candidates in the iteration are ranked by `routing_score` descending, then by `cost_estimate_cents` ascending, then by `coverage_units` descending, then by node `created_at` ascending — never by node `id` — and each is given its 1-based `rank` within the iteration."
        PRD §3.4: "The winner's `selected` flag is set to true and its `assigned_units` is set equal to its `coverage_units`."
        PRD §3.4: "When the loop ends, `unfulfillable_units` records whatever remaining demand is left, and `selected_store_count` and `planned_split_count` both equal the number of nodes selected."
        PRD §3.4: "Otherwise a `COMMIT` run's `status` is `COMMITTED`."
        PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."
        PRD §3.2: "A demand line's `open_units` is always its `quantity` less `assigned_units`, less `shipped_units`, less `cancelled_units`, less `dc_fallback_units`."

        Dropping the buffer to 4 leaves available_to_promise_units at exactly 1,
        which satisfies the clause and lets the very same run commit.

        Design: Difficulty/boundary_precision_check/routing_run_flips_at_available_to_promise_exactly_zero
        """
        ctx = _setup_single_node_order(on_hand_units=5, safety_stock_units=5)

        adjusted = adjust_inventory(
            ctx["inventory"]["id"], 5, "CYCLE_COUNT", safety_stock_units=4
        )
        assert adjusted["safety_stock_units"] == 4, "the replacement buffer is stored"
        assert adjusted["last_adjustment_reason"] == "CYCLE_COUNT", (
            "last_adjustment_reason records the supplied reason"
        )
        assert adjusted["available_to_promise_units"] == 1, (
            "on_hand 5 minus reserved 0 minus safety 4 is exactly 1 promise-able unit"
        )

        run = validate_success(
            api.create_routing_run(
                ctx["order"]["id"],
                {
                    "mode": "COMMIT",
                    "expected_order_version": order_version(ctx["order"]["id"]),
                },
                PLANNER,
            ),
            201,
        )

        assert run["status"] == "COMMITTED", (
            f"a COMMIT run that selected a node is COMMITTED, got {run['status']}"
        )
        assert run["selected_store_count"] == 1, "exactly one node was selected"
        assert run["unfulfillable_units"] == 0, "no remaining demand is left over"

        candidates = find_routing_candidates(routing_run_id=run["id"])
        assert len(candidates) == 1, f"expected exactly one candidate, got {len(candidates)}"
        candidate = candidates[0]
        assert candidate["eligible"] is True, (
            "one promise-able unit satisfies the eighth eligibility clause"
        )
        assert candidate["ineligible_reason"] is None, (
            "an eligible candidate records no ineligible_reason"
        )
        assert candidate["coverage_units"] == 1, (
            "coverage_units is the smallest of promise-able 1, capacity, labour and demand 1"
        )
        assert candidate["coverage_ratio"] == pytest.approx(1.0000, abs=0.0001), (
            "1 covered unit of 1 remaining demand unit is a coverage_ratio of 1.0000"
        )
        assert candidate["rank"] == 1, "the only eligible candidate ranks 1"
        assert candidate["selected"] is True, "the rank-1 candidate wins the iteration"

        assignment = find_assignment(
            order_id=ctx["order"]["id"], store_id=ctx["store"]["id"]
        )
        assert assignment["assigned_units"] == 1, (
            "the winner's assigned_units equals its coverage_units"
        )

        inventory = read_inventory(ctx["inventory"]["id"])
        assert inventory["reserved_units"] == 1, (
            "the ASSIGNED assignment line holds one reserved unit"
        )
        assert inventory["available_to_promise_units"] == 0, (
            "on_hand 5 minus reserved 1 minus safety 4 leaves 0 promise-able units"
        )

        order = read_order(ctx["order"]["id"])
        assert order["routing_status"] == "ROUTED", (
            f"covered units plus cancelled units equals total_units, got "
            f"{order['routing_status']}"
        )
        line = read_order_line(ctx["line"]["id"])
        assert line["open_units"] == 0, "the single unit is no longer open"


# ======================================================================
# The same-day cutoff minute itself is inside the window
# ======================================================================


class TestPackCutoffMinuteBoundary:
    def test_pack_is_allowed_at_exactly_the_cutoff_minute(self):
        """PRD §2.6: "Each node publishes a same-day cutoff as `cutoff_utc_minutes`, an integer from 0 to 1439 inclusive counting minutes after midnight UTC."
        PRD §2.6: "In-store work — accepting, picking, packing and shipping — is permitted only while the clock's minute-of-day, taken as the whole number of minutes elapsed since midnight UTC with any seconds discarded, is less than or equal to that node's `cutoff_utc_minutes`."
        PRD §2.6: "The cutoff minute itself is inside the window."
        PRD §3.5: "From either `PICKED` or `SHORT_PICKED`, the associate records packing with the `package_type` actually used, moving the assignment to `PACKED`."
        PRD §3.5: "Packing requires, in this order, the acting node to match, the assignment to be at `PICKED` or `SHORT_PICKED`, and the clock's minute-of-day to be within the node's cutoff."
        PRD §3.5: "On success `packed_at` is set to the clock instant, `package_type` is stored, and `labor_minutes_actual` is computed as the elapsed time from `accepted_at` to `packed_at` expressed in whole minutes with any remaining seconds discarded."
        PRD §3.5: "The packaging row's `on_hand_units` is decremented by 1, its `lifetime_consumed_units` is incremented by 1, and its `reorder_flag` is re-derived."
        PRD §3.5: "`final_cost_cents` is deliberately *not* written at pack — the final cost variant is sealed at ship — and because both branches rejoin here, that variant consumes `picked_units` regardless of which branch arrived."

        The node's cutoff_utc_minutes is 1020, so 17:00:00Z is minute-of-day 1020
        — the cutoff minute itself, which is inside the window.

        Design: Difficulty/boundary_precision_check/pack_allowed_at_exactly_the_cutoff_minute_and_refused_one_minute_later
        """
        ctx = _setup_picked_assignment_at_cutoff_node()
        assert ctx["store"]["cutoff_utc_minutes"] == 1020, (
            "the node publishes minute 1020 (17:00 UTC) as its same-day cutoff"
        )

        set_clock("2026-08-03T17:00:00Z")
        packed = pack(ctx["assignment"]["id"], ctx["store"]["id"], "MEDIUM_BOX")

        assert packed["status"] == "PACKED", (
            f"a pack at exactly the cutoff minute must succeed, got {packed['status']}"
        )
        _assert_instant(packed["packed_at"], "2026-08-03T17:00:00", "packed_at")
        assert packed["labor_minutes_actual"] == pytest.approx(475.00, abs=0.01), (
            "09:05 accepted_at to 17:00 packed_at is 475 whole minutes"
        )
        assert packed["package_type"] == "MEDIUM_BOX", (
            "the package_type actually used is stored"
        )
        assert packed["final_cost_cents"] is None, (
            "final_cost_cents is deliberately not written at pack"
        )

        supply = read_packaging(ctx["supply"]["id"])
        assert supply["on_hand_units"] == 4, (
            "the packaging row's on_hand_units is decremented by 1 from 5"
        )
        assert supply["lifetime_consumed_units"] == 1, (
            "lifetime_consumed_units is incremented by 1"
        )

    def test_pack_is_refused_one_minute_after_the_cutoff_minute(self, api):
        """PRD §2.6: "Each node publishes a same-day cutoff as `cutoff_utc_minutes`, an integer from 0 to 1439 inclusive counting minutes after midnight UTC."
        PRD §2.6: "In-store work — accepting, picking, packing and shipping — is permitted only while the clock's minute-of-day, taken as the whole number of minutes elapsed since midnight UTC with any seconds discarded, is less than or equal to that node's `cutoff_utc_minutes`."
        PRD §2.6: "Work attempted after it is rejected with `ERR_STORE_CUTOFF_PASSED` (HTTP 422)."
        PRD §3.5: "Packing requires, in this order, the acting node to match, the assignment to be at `PICKED` or `SHORT_PICKED`, and the clock's minute-of-day to be within the node's cutoff."
        PRD §3.5: "On success `packed_at` is set to the clock instant, `package_type` is stored, and `labor_minutes_actual` is computed as the elapsed time from `accepted_at` to `packed_at` expressed in whole minutes with any remaining seconds discarded."
        PRD §3.5: "The packaging row's `on_hand_units` is decremented by 1, its `lifetime_consumed_units` is incremented by 1, and its `reorder_flag` is re-derived."

        17:01:00Z is minute-of-day 1021, one minute past the node's cutoff of
        1020, so the identical pack is refused and nothing is consumed.

        Design: Difficulty/boundary_precision_check/pack_allowed_at_exactly_the_cutoff_minute_and_refused_one_minute_later
        """
        ctx = _setup_picked_assignment_at_cutoff_node()
        assert ctx["store"]["cutoff_utc_minutes"] == 1020, (
            "the node publishes minute 1020 (17:00 UTC) as its same-day cutoff"
        )

        set_clock("2026-08-03T17:01:00Z")
        response = api.pack_assignment(
            ctx["assignment"]["id"],
            {"package_type": "MEDIUM_BOX"},
            make_store_associate_headers(ctx["store"]["id"]),
        )
        validate_error(response, "ERR_STORE_CUTOFF_PASSED")

        assignment = read_assignment(ctx["assignment"]["id"])
        assert assignment["status"] == "PICKED", (
            f"a refused pack leaves the assignment at PICKED, got {assignment['status']}"
        )
        assert assignment["packed_at"] is None, (
            "packed_at is only set on a successful pack"
        )
        assert assignment["labor_minutes_actual"] is None, (
            "labor_minutes_actual is only computed on a successful pack"
        )
        assert assignment["package_type"] is None, (
            "package_type is only stored on a successful pack"
        )

        supply = read_packaging(ctx["supply"]["id"])
        assert supply["on_hand_units"] == 5, (
            "a refused pack consumes no packaging unit"
        )
        assert supply["lifetime_consumed_units"] == 0, (
            "lifetime_consumed_units only moves on a successful pack"
        )


# ======================================================================
# fill_rate at the 0.9000 floor versus below it
# ======================================================================


class TestFillRateFloorBoundary:
    def test_fill_rate_exactly_at_the_floor_does_not_raise_a_breach(self):
        """PRD §3.1: "Registration also opens the node's first performance window at the network's current epoch — the highest `epoch` across all existing windows, or 1 when no window exists anywhere yet — with `opened_at_utc` set to the clock instant and `closed_at_utc` null."
        PRD §3.9: "It executes seven steps in exactly this order, and it answers with the windows it closed, in ascending node `created_at` order."
        PRD §3.9: "The window's assignment set is the assignments whose `store_id` is this node and whose stamped `epoch` equals the window's `epoch` — the stamp taken at assignment creation, never the node's current epoch."
        PRD §3.9: "From that set: `assignments_created` is the count of all of them; `assignments_shipped`, `assignments_rejected` and `assignments_cancelled` are the counts at `status` `SHIPPED`, `REJECTED` and `CANCELLED` respectively; `units_promised` is the sum of `assigned_units` over all of them; and `units_shipped` is the sum of `picked_units` over those at `SHIPPED`."
        PRD §3.9: "`fill_rate` is exactly 1.0000 when `units_promised` is 0, and otherwise `units_shipped` divided by `units_promised` rounded half-up to four decimal places."
        PRD §3.9: "`avg_cycle_time_minutes` is exactly 0.00 when `assignments_shipped` is 0, and otherwise the sum of `cycle_time_minutes` over the shipped assignments divided by `assignments_shipped`, rounded half-up to two decimal places."
        PRD §3.9: "`cancellation_rate` is exactly 0.0000 when `assignments_created` is 0, and otherwise `assignments_rejected` plus `assignments_cancelled`, divided by `assignments_created`, rounded half-up to four decimal places."
        PRD §3.9: "`breach_flags` is then built as a subset of three markers appended in this fixed order: `FILL_RATE` when `assignments_shipped` is at least 1 and `fill_rate` is strictly below 0.9000; `CYCLE_TIME` when `assignments_shipped` is at least 1 and `avg_cycle_time_minutes` is strictly greater than four hours; and `CANCELLATION_RATE` when `assignments_created` is at least 1 and `cancellation_rate` is strictly greater than 0.0500."
        PRD §3.9: "`breached` is true exactly when `breach_flags` is non-empty."
        PRD §3.9: "Otherwise it is `DEACTIVATION` when the window is breached and the node's `consecutive_breach_windows` plus 1 reaches 2; `PROBATION` when the window is breached, the node's `node_status` is `ELIGIBLE`, and `consecutive_breach_windows` plus 1 is still below 2; `RECOVERY` when the window is not breached and the node's `node_status` is `PROBATION`; and `NONE` in every other case."
        PRD §3.9: "`consecutive_breach_windows` is then set to 0 when the window was non-empty and not breached, incremented by 1 when the window was non-empty and breached, and left completely unchanged when the window was empty — so an empty window never changes posture and never resets the breach counter."
        PRD §3.9: "Each window's `status` becomes `CLOSED`, its `closed_at_utc` is set to the clock instant, and each node's `units_committed_epoch` is reset to 0."
        PRD §3.6: "The assignment's `status` becomes `SHIPPED`, `shipped_at` is set to the clock instant, `carrier_pickup_id` is stored, and `cycle_time_minutes` is computed as the elapsed time from `created_at` to `shipped_at` in whole minutes with remaining seconds discarded."

        9 units shipped of 10 promised is a fill_rate of exactly 0.9000, which is
        not strictly below the floor, so no FILL_RATE marker is raised.

        Design: Difficulty/boundary_precision_check/fill_rate_exactly_at_the_floor_does_not_breach_while_one_tenth_lower_does
        """
        ctx = _close_epoch_with_one_shipped_and_one_open(9, 1)
        windows = ctx["closed_windows"]
        assert len(windows) == 1, f"exactly one window was closed, got {len(windows)}"
        window = windows[0]

        assert window["store_id"] == ctx["store"]["id"], (
            "the closed window belongs to the node under test"
        )
        assert window["epoch"] == 1, "the node's first window sits at epoch 1"
        assert window["status"] == "CLOSED", (
            f"the operations run closes the window, got {window['status']}"
        )
        assert window["assignments_created"] == 2, (
            "both epoch-1 assignments are in the window's assignment set"
        )
        assert window["assignments_shipped"] == 1, "exactly one assignment reached SHIPPED"
        assert window["units_promised"] == 10, (
            "units_promised is 9 plus 1 assigned units across the set"
        )
        assert window["units_shipped"] == 9, (
            "units_shipped is the picked_units of the one shipped assignment"
        )
        assert window["fill_rate"] == pytest.approx(0.9000, abs=0.0001), (
            f"9 of 10 units is a fill_rate of 0.9000, got {window['fill_rate']}"
        )
        assert window["avg_cycle_time_minutes"] == pytest.approx(30.00, abs=0.01), (
            "09:00 created_at to 09:30 shipped_at is a 30 minute cycle time"
        )
        assert window["cancellation_rate"] == pytest.approx(0.0000, abs=0.0001), (
            "no assignment was rejected or cancelled"
        )
        assert window["breach_flags"] == [], (
            "a fill_rate of exactly 0.9000 is not strictly below the floor, and "
            f"neither other marker applies, got {window['breach_flags']}"
        )
        assert window["breached"] is False, "breached is false while breach_flags is empty"
        assert window["node_action"] == "NONE", (
            f"a non-breached window at an ELIGIBLE node takes no action, got "
            f"{window['node_action']}"
        )

        store = ctx["store"]
        assert store["node_status"] == "ELIGIBLE", (
            f"the node keeps its ELIGIBLE posture, got {store['node_status']}"
        )
        assert store["consecutive_breach_windows"] == 0, (
            "a non-empty, non-breached window resets the breach counter to 0"
        )
        assert store["units_committed_epoch"] == 0, (
            "closing the window resets units_committed_epoch to 0"
        )

        open_assignment = ctx["open_assignment"]
        assert open_assignment["status"] == "ASSIGNED", (
            "the second task never left ASSIGNED, so none of its units shipped"
        )
        assert open_assignment["epoch"] == 1, (
            "the second assignment is stamped with the same epoch-1 window"
        )

    def test_fill_rate_below_the_floor_raises_the_breach_and_puts_the_node_on_probation(
        self,
    ):
        """PRD §3.9: "It executes seven steps in exactly this order, and it answers with the windows it closed, in ascending node `created_at` order."
        PRD §3.9: "The window's assignment set is the assignments whose `store_id` is this node and whose stamped `epoch` equals the window's `epoch` — the stamp taken at assignment creation, never the node's current epoch."
        PRD §3.9: "From that set: `assignments_created` is the count of all of them; `assignments_shipped`, `assignments_rejected` and `assignments_cancelled` are the counts at `status` `SHIPPED`, `REJECTED` and `CANCELLED` respectively; `units_promised` is the sum of `assigned_units` over all of them; and `units_shipped` is the sum of `picked_units` over those at `SHIPPED`."
        PRD §3.9: "`fill_rate` is exactly 1.0000 when `units_promised` is 0, and otherwise `units_shipped` divided by `units_promised` rounded half-up to four decimal places."
        PRD §3.9: "`avg_cycle_time_minutes` is exactly 0.00 when `assignments_shipped` is 0, and otherwise the sum of `cycle_time_minutes` over the shipped assignments divided by `assignments_shipped`, rounded half-up to two decimal places."
        PRD §3.6: "The assignment's `status` becomes `SHIPPED`, `shipped_at` is set to the clock instant, `carrier_pickup_id` is stored, and `cycle_time_minutes` is computed as the elapsed time from `created_at` to `shipped_at` in whole minutes with remaining seconds discarded."
        PRD §3.9: "`breach_flags` is then built as a subset of three markers appended in this fixed order: `FILL_RATE` when `assignments_shipped` is at least 1 and `fill_rate` is strictly below 0.9000; `CYCLE_TIME` when `assignments_shipped` is at least 1 and `avg_cycle_time_minutes` is strictly greater than four hours; and `CANCELLATION_RATE` when `assignments_created` is at least 1 and `cancellation_rate` is strictly greater than 0.0500."
        PRD §3.9: "`breached` is true exactly when `breach_flags` is non-empty."
        PRD §3.9: "Otherwise it is `DEACTIVATION` when the window is breached and the node's `consecutive_breach_windows` plus 1 reaches 2; `PROBATION` when the window is breached, the node's `node_status` is `ELIGIBLE`, and `consecutive_breach_windows` plus 1 is still below 2; `RECOVERY` when the window is not breached and the node's `node_status` is `PROBATION`; and `NONE` in every other case."
        PRD §3.9: "A `PROBATION` action moves the node `ELIGIBLE → PROBATION` and sets `consecutive_breach_windows` to 1."

        4 units shipped of 5 promised is a fill_rate of 0.8000, strictly below the
        0.9000 floor, so the FILL_RATE marker is raised on the very same close.

        Design: Difficulty/boundary_precision_check/fill_rate_exactly_at_the_floor_does_not_breach_while_one_tenth_lower_does
        """
        ctx = _close_epoch_with_one_shipped_and_one_open(4, 1)
        windows = ctx["closed_windows"]
        assert len(windows) == 1, f"exactly one window was closed, got {len(windows)}"
        window = windows[0]

        assert window["store_id"] == ctx["store"]["id"], (
            "the closed window belongs to the node under test"
        )
        assert window["units_promised"] == 5, (
            "units_promised is 4 plus 1 assigned units across the set"
        )
        assert window["units_shipped"] == 4, (
            "units_shipped is the picked_units of the one shipped assignment"
        )
        assert window["fill_rate"] == pytest.approx(0.8000, abs=0.0001), (
            f"4 of 5 units is a fill_rate of 0.8000, got {window['fill_rate']}"
        )
        assert window["avg_cycle_time_minutes"] == pytest.approx(30.00, abs=0.01), (
            "09:00 created_at to 09:30 shipped_at is a 30 minute cycle time"
        )
        assert window["breach_flags"] == ["FILL_RATE"], (
            "a fill_rate strictly below 0.9000 raises FILL_RATE and nothing else, got "
            f"{window['breach_flags']}"
        )
        assert window["breached"] is True, (
            "breached is true exactly when breach_flags is non-empty"
        )
        assert window["node_action"] == "PROBATION", (
            "a first breach at an ELIGIBLE node is a PROBATION action, got "
            f"{window['node_action']}"
        )

        store = ctx["store"]
        assert store["node_status"] == "PROBATION", (
            f"the PROBATION action moves the node off ELIGIBLE, got {store['node_status']}"
        )
        assert store["consecutive_breach_windows"] == 1, (
            "the PROBATION action sets consecutive_breach_windows to 1"
        )


# ======================================================================
# Concurrent pick labour at exactly the cap versus over it
# ======================================================================


class TestConcurrentLaborCapBoundary:
    def test_accept_is_allowed_when_concurrent_labor_exactly_equals_the_cap(self):
        """PRD §3.5: "A `StoreAssociate` takes ownership of the task by accepting it, moving `ASSIGNED → ACCEPTED` and setting `accepted_at` to the clock instant."
        PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."
        PRD §3.5: "Take the candidate interval running from the current clock instant, inclusive, up to but excluding this assignment's `pick_deadline_utc`."
        PRD §3.5: "Consider the node's other assignments whose `status` is `ACCEPTED`, `PICKED` or `SHORT_PICKED`; one of them overlaps the candidate interval when its `accepted_at` is strictly before the candidate interval's end and the candidate interval's start is strictly before its own `pick_deadline_utc` — half-open geometry with no additional buffer."
        PRD §3.5: "The concurrent load is the sum of `labor_minutes_reserved` over those overlapping assignments plus this assignment's own `labor_minutes_reserved`; the cap is half the node's `staffed_labor_minutes` with any fraction discarded."
        PRD §3.5: "When the load strictly exceeds the cap the accept is refused with `ERR_LABOR_WINDOW_OVERSUBSCRIBED`; a load exactly equal to the cap is allowed."

        The node is staffed for 60 minutes, so the cap is exactly 30. Accepting a
        12-minute task and then an 18-minute task lands the load on exactly 30.

        Design: Difficulty/boundary_precision_check/accept_allowed_at_concurrent_labor_exactly_equal_to_the_cap
        """
        ctx = _setup_kiosk_with_three_assignments()
        store = ctx["store"]
        first, second, third = ctx["assignments"]

        assert store["staffed_labor_minutes"] == 60, (
            "the node is staffed for 60 minutes, so the concurrent cap is 30"
        )
        assert first["labor_minutes_reserved"] == pytest.approx(12.00, abs=0.01), (
            "2 units at standard 6 plus 3 per unit is a 12.00 minute labour standard"
        )
        assert second["labor_minutes_reserved"] == pytest.approx(18.00, abs=0.01), (
            "4 units at standard 6 plus 3 per unit is an 18.00 minute labour standard"
        )

        accepted_first = accept(first["id"], store["id"])
        assert accepted_first["status"] == "ACCEPTED", (
            "a load of 12.00 against a cap of 30 is accepted, got "
            f"{accepted_first['status']}"
        )

        accepted_second = accept(second["id"], store["id"])
        assert accepted_second["status"] == "ACCEPTED", (
            "an overlapping load of 12.00 plus 18.00 is exactly the cap of 30 and is "
            f"allowed, got {accepted_second['status']}"
        )
        _assert_instant(
            accepted_second["accepted_at"], "2026-08-03T09:05:00", "accepted_at"
        )
        assert accepted_second["labor_minutes_reserved"] == pytest.approx(
            18.00, abs=0.01
        ), "the labour standard is committed once and never rewritten by the accept"

        assert read_assignment(third["id"])["status"] == "ASSIGNED", (
            "the third task was never accepted in this scenario"
        )

    def test_accept_is_refused_when_concurrent_labor_exceeds_the_cap_by_nine_minutes(
        self, api
    ):
        """PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."
        PRD §3.5: "Consider the node's other assignments whose `status` is `ACCEPTED`, `PICKED` or `SHORT_PICKED`; one of them overlaps the candidate interval when its `accepted_at` is strictly before the candidate interval's end and the candidate interval's start is strictly before its own `pick_deadline_utc` — half-open geometry with no additional buffer."
        PRD §3.5: "The concurrent load is the sum of `labor_minutes_reserved` over those overlapping assignments plus this assignment's own `labor_minutes_reserved`; the cap is half the node's `staffed_labor_minutes` with any fraction discarded."
        PRD §3.5: "When the load strictly exceeds the cap the accept is refused with `ERR_LABOR_WINDOW_OVERSUBSCRIBED`; a load exactly equal to the cap is allowed."
        PRD §3.5: "A `StoreAssociate` takes ownership of the task by accepting it, moving `ASSIGNED → ACCEPTED` and setting `accepted_at` to the clock instant."

        With two overlapping tasks already on the pick floor at 12.00 and 18.00,
        a third task of 9.00 raises the load to 39.00 against the cap of 30.

        Design: Difficulty/boundary_precision_check/accept_allowed_at_concurrent_labor_exactly_equal_to_the_cap
        """
        ctx = _setup_kiosk_with_three_assignments()
        store = ctx["store"]
        first, second, third = ctx["assignments"]

        accept(first["id"], store["id"])
        accept(second["id"], store["id"])
        assert third["labor_minutes_reserved"] == pytest.approx(9.00, abs=0.01), (
            "1 unit at standard 6 plus 3 per unit is a 9.00 minute labour standard"
        )

        response = api.accept_assignment(
            third["id"], make_store_associate_headers(store["id"])
        )
        validate_error(response, "ERR_LABOR_WINDOW_OVERSUBSCRIBED")

        refused = read_assignment(third["id"])
        assert refused["status"] == "ASSIGNED", (
            f"a refused accept leaves the assignment at ASSIGNED, got {refused['status']}"
        )
        assert refused["accepted_at"] is None, (
            "accepted_at is only set on a successful accept"
        )
        assert read_assignment(first["id"])["status"] == "ACCEPTED", (
            "the already accepted task is untouched by the refusal"
        )
        assert read_assignment(second["id"])["status"] == "ACCEPTED", (
            "the already accepted task is untouched by the refusal"
        )

    def test_accept_succeeds_once_the_overlapping_work_has_left_the_pick_floor(self):
        """PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."
        PRD §3.5: "Consider the node's other assignments whose `status` is `ACCEPTED`, `PICKED` or `SHORT_PICKED`; one of them overlaps the candidate interval when its `accepted_at` is strictly before the candidate interval's end and the candidate interval's start is strictly before its own `pick_deadline_utc` — half-open geometry with no additional buffer."
        PRD §3.5: "Assignments at `PACKED` have left the pick floor and are excluded."
        PRD §3.5: "The concurrent load is the sum of `labor_minutes_reserved` over those overlapping assignments plus this assignment's own `labor_minutes_reserved`; the cap is half the node's `staffed_labor_minutes` with any fraction discarded."
        PRD §3.5: "When the load strictly exceeds the cap the accept is refused with `ERR_LABOR_WINDOW_OVERSUBSCRIBED`; a load exactly equal to the cap is allowed."
        PRD §2.9: "A node's `reserved_labor_minutes` equals the sum of `labor_minutes_reserved` over that node's assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."

        Once the 12.00 minute task reaches PACKED it is excluded from the load,
        which drops to 18.00 plus 9.00 — 27.00 against the cap of 30 — so the
        same third accept now succeeds.

        Design: Difficulty/boundary_precision_check/accept_allowed_at_concurrent_labor_exactly_equal_to_the_cap
        """
        ctx = _setup_kiosk_with_three_assignments()
        store = ctx["store"]
        first, second, third = ctx["assignments"]

        accept(first["id"], store["id"])
        accept(second["id"], store["id"])
        pick_full(first["id"], store["id"])
        packed = pack(first["id"], store["id"], "MEDIUM_BOX")
        assert packed["status"] == "PACKED", (
            f"the first task must reach PACKED, got {packed['status']}"
        )

        accepted_third = accept(third["id"], store["id"])
        assert accepted_third["status"] == "ACCEPTED", (
            "with the PACKED task excluded the load is 18.00 plus 9.00 == 27.00, "
            f"inside the cap of 30, got {accepted_third['status']}"
        )
        assert accepted_third["labor_minutes_reserved"] == pytest.approx(9.00, abs=0.01), (
            "the labour standard is committed once and never rewritten by the accept"
        )
        assert read_assignment(first["id"])["labor_minutes_reserved"] == pytest.approx(
            12.00, abs=0.01
        ), "packing never re-prices the labour standard"

        node = read_store(store["id"])
        assert node["reserved_labor_minutes"] == pytest.approx(39.00, abs=0.01), (
            "PACKED, ACCEPTED and ACCEPTED all still hold their labour standard: "
            "12.00 plus 18.00 plus 9.00"
        )
