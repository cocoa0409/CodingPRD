"""Pricing a draw under both policies, and the balance a cancellation gives
back to the pools."""

from test_helpers import (
    assert_allocation_line,
    assert_instant_equals,
    assert_order_dimensions,
    assert_supply_conservation,
    cancel_order_payload,
    place_order,
    read_order,
    read_supply,
    setup_allocated_order,
    setup_two_competing_orders,
    validate_paginated,
    validate_success,
)


class TestPreviewUnderBothPolicies:
    """The same order prices differently under the two allocation policies."""

    def test_waterfall_preview_grants_the_full_remaining_need(
        self, api, supply_planner_headers
    ):
        """Under PRIORITY_WATERFALL, granted_units is the smaller of
        remaining_need and kit_capacity — the order in front takes everything it
        can carry and later orders live on whatever is left, which is why
        priority_score decides who is served first.

        Design: Difficulty/dual_variant_calc/allocation_preview_waterfall_grants_80_prorata_grants_57
        """
        scenario = setup_two_competing_orders()
        order_a = scenario["order_a"]

        preview = validate_success(
            api.get_allocation_preview(
                order_a["id"],
                supply_planner_headers,
                params={"policy": "PRIORITY_WATERFALL"},
            )
        )

        assert preview["order_id"] == order_a["id"]
        assert preview["policy"] == "PRIORITY_WATERFALL"
        assert preview["compressor_pool"] == 100
        assert preview["board_pool"] == 100
        assert preview["kit_capacity"] == 100, "one kit needs one of each component"
        assert preview["remaining_need"] == 80
        assert preview["total_open_demand"] == 140, "both open orders are counted"
        assert preview["granted_units"] == 80, (
            f"the waterfall hands the front order its whole need, got "
            f"{preview['granted_units']}"
        )

    def test_prorata_preview_truncates_the_fair_share_to_57_units(
        self, api, supply_planner_headers
    ):
        """Under DEMAND_PRORATA, a fair share is computed first by multiplying
        kit_capacity by remaining_need, dividing by total_open_demand, and
        truncating downward to a whole unit; granted_units is then the smaller of
        remaining_need and that fair share.

        Design: Difficulty/dual_variant_calc/allocation_preview_waterfall_grants_80_prorata_grants_57
        """
        scenario = setup_two_competing_orders()
        order_a = scenario["order_a"]

        preview = validate_success(
            api.get_allocation_preview(
                order_a["id"],
                supply_planner_headers,
                params={"policy": "DEMAND_PRORATA"},
            )
        )

        assert preview["policy"] == "DEMAND_PRORATA"
        assert preview["kit_capacity"] == 100
        assert preview["remaining_need"] == 80
        assert preview["total_open_demand"] == 140
        assert preview["granted_units"] == 57, (
            "100 kits times 80 units of need over 140 of open demand truncates "
            f"to 57, got {preview['granted_units']}"
        )

    def test_pricing_the_order_twice_stores_nothing(self, api, supply_planner_headers):
        """A computed allocation-preview read prices what a given order would
        receive without drawing anything: it accepts an optional policy override
        so that both variants can be compared. It stores nothing and increments
        no version.

        Design: Difficulty/dual_variant_calc/allocation_preview_waterfall_grants_80_prorata_grants_57
        """
        scenario = setup_two_competing_orders()
        order_a = scenario["order_a"]

        waterfall = validate_success(
            api.get_allocation_preview(
                order_a["id"],
                supply_planner_headers,
                params={"policy": "PRIORITY_WATERFALL"},
            )
        )
        prorata = validate_success(
            api.get_allocation_preview(
                order_a["id"],
                supply_planner_headers,
                params={"policy": "DEMAND_PRORATA"},
            )
        )
        assert waterfall["granted_units"] == 80
        assert prorata["granted_units"] == 57

        for pool_id in (scenario["compressor"]["id"], scenario["control_board"]["id"]):
            pool = read_supply(pool_id)
            assert pool["version"] == 1, "pricing a draw leaves the pool version alone"
            assert pool["reserved_units"] == 0
            assert pool["available_units"] == 100
            assert pool["status"] == "ACTIVE"

        stored_order = read_order(order_a["id"])
        assert_order_dimensions(stored_order, "UNALLOCATED", "PENDING")
        assert stored_order["version"] == order_a["version"]

        _, lines_meta = validate_paginated(
            api.list_order_allocation_lines(order_a["id"], supply_planner_headers)
        )
        assert lines_meta["total_count"] == 0, "no line was drawn by a preview"


class TestCancellationRestoresConservation:
    """Cancelling a fully allocated order gives the units back."""

    def test_cancellation_releases_every_line_and_restores_the_identity(
        self, api, distributor_rep_headers, supply_planner_headers
    ):
        """Every allocation line of the order still in RESERVED becomes RELEASED
        with closed_reason set to ORDER_CANCELLED, processed oldest first; each
        touched pool recomputes reserved_units and available_units, returns
        EXHAUSTED → ACTIVE when available_units ends above zero, and increments
        its version, restoring the conserved identity of §2.9. For a component
        supply, effective_allocatable_units equals available_units plus
        reserved_units plus committed_units; a derate that would drive
        available_units below zero is never stored as a negative balance, and the
        cascade revokes reserved lines until the identity holds with
        available_units at zero or above.

        Design: Difficulty/compensating_invariant/order_cancellation_restores_supply_conservation_identity
        """
        scenario = setup_allocated_order(
            requested_units=100,
            compressor_units=100,
            board_units=100,
            priority_score=75,
        )
        order = scenario["order"]
        assert_order_dimensions(order, "FULLY_ALLOCATED", "PENDING")
        assert order["allocated_units"] == 100
        assert read_supply(scenario["compressor"]["id"])["status"] == "EXHAUSTED"

        cancelled = validate_success(
            api.cancel_distributor_order(
                order["id"],
                cancel_order_payload("Distributor withdrew the pre-season order"),
                distributor_rep_headers,
            )
        )
        assert_order_dimensions(cancelled, "UNALLOCATED", "CANCELLED")
        assert cancelled["allocated_units"] == 0
        assert_instant_equals(
            cancelled["cancelled_at"], "2026-08-01T00:00:00Z", "cancelled_at"
        )

        lines, lines_meta = validate_paginated(
            api.list_order_allocation_lines(order["id"], supply_planner_headers)
        )
        assert lines_meta["total_count"] == 2, "one compressor line and one board line"
        for line in lines:
            assert_allocation_line(line)
            assert line["status"] == "RELEASED"
            assert line["closed_reason"] == "ORDER_CANCELLED"

        for pool_id in (scenario["compressor"]["id"], scenario["control_board"]["id"]):
            pool = read_supply(pool_id)
            assert pool["status"] == "ACTIVE", "the pool comes back from EXHAUSTED"
            assert pool["reserved_units"] == 0
            assert pool["committed_units"] == 0
            assert pool["available_units"] == 100
            assert_supply_conservation(pool)

    def test_released_units_are_drawable_by_the_next_order(
        self, api, distributor_rep_headers, supply_planner_headers
    ):
        """Because one finished unit consumes exactly one compressor and exactly
        one control board, kit_capacity is the smaller of compressor_pool and
        board_pool. total_open_demand is the sum, over every distributor order
        for the same platform_id and the same requested_delivery_month whose
        fulfillment_status is PENDING and whose allocation_status is not
        FULLY_ALLOCATED, of that order's requested_units less its allocated_units
        — and the order being allocated is itself included in that sum.

        Design: Difficulty/compensating_invariant/order_cancellation_restores_supply_conservation_identity
        """
        scenario = setup_allocated_order(
            requested_units=100,
            compressor_units=100,
            board_units=100,
            priority_score=75,
        )
        validate_success(
            api.cancel_distributor_order(
                scenario["order"]["id"],
                cancel_order_payload("Distributor withdrew the pre-season order"),
                distributor_rep_headers,
            )
        )

        replacement = place_order(
            scenario["platform"]["id"],
            requested_units=60,
            priority_score=50,
            distributor_code="DIST-SE-3",
        )
        preview = validate_success(
            api.get_allocation_preview(replacement["id"], supply_planner_headers)
        )

        assert preview["compressor_pool"] == 100, "the released units are visible again"
        assert preview["board_pool"] == 100
        assert preview["kit_capacity"] == 100
        assert preview["remaining_need"] == 60
        assert preview["total_open_demand"] == 60, (
            "the cancelled order no longer counts as open demand"
        )
        assert preview["granted_units"] == 60
