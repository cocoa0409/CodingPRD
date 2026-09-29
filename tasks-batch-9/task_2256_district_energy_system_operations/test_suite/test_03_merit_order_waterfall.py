"""The cheapest-first dispatch waterfall, storage sizing and the stability floor."""

from test_helpers import (
    assert_dispatch_order,
    assert_plan_metrics,
    campus_dispatch_stack,
    industrial_boundary_stack,
    plan_in_state,
    plan_orders,
    read_asset,
)


class TestStorageNameplateSizing:
    """Nested minima decide what each machine may offer and what it takes."""

    def test_storage_is_sized_from_nameplate_capacity_over_the_four_hour_window(self):
        """The thermal store offers the lesser of its rating and its tank quarter.

        PRD: "A `THERMAL_STORAGE` asset offers the lesser of its
        `rated_capacity_kw` and its `storage_capacity_kwh` divided by the
        four-hour storage discharge window, with that quotient rounded half-up to
        two decimal places".

        Design: Difficulty/combinatorial_formula/merit_order_nested_min_max_with_storage_nameplate_sizing
        """
        stack = campus_dispatch_stack(plan_state="OPTIMIZED")

        orders = plan_orders(stack["plan"]["id"])

        assert len(orders) == 3, f"expected three dispatch orders, got {len(orders)}"
        assert_dispatch_order(
            orders[0],
            asset_id=stack["storage"]["id"],
            merit_rank=1,
            allocated_kw=1000.00,
            block_energy_mwh=4.000,
            discharged_kwh=4000.00,
            order_cost=24.00,
            order_emissions_kg=0.00,
        )

    def test_the_waterfall_ranks_cheapest_first_and_trims_the_last_block(self):
        """Storage, then cogeneration, then biomass taking only the remainder.

        PRD: "The block allocated to the asset is the lesser of that effective
        capacity and the remaining demand."

        Design: Difficulty/combinatorial_formula/merit_order_nested_min_max_with_storage_nameplate_sizing
        """
        stack = campus_dispatch_stack(plan_state="OPTIMIZED")

        orders = plan_orders(stack["plan"]["id"])

        assert_dispatch_order(
            orders[1],
            asset_id=stack["chp"]["id"],
            merit_rank=2,
            allocated_kw=1200.00,
            block_energy_mwh=28.800,
            discharged_kwh=0.00,
            order_cost=1152.00,
            order_emissions_kg=5904.00,
        )
        assert_dispatch_order(
            orders[2],
            asset_id=stack["biomass_boiler"]["id"],
            merit_rank=3,
            allocated_kw=327.20,
            block_energy_mwh=7.853,
            discharged_kwh=0.00,
            order_cost=408.36,
            order_emissions_kg=219.88,
        )

    def test_the_dearest_machine_is_never_reached_once_demand_is_covered(self):
        """The oil boiler earns no order because the remainder fell to zero.

        PRD: "The remaining demand is then reduced by the allocated block and
        rounded half-up to two decimal places, and the waterfall stops as soon as
        that remainder falls to zero or below."

        Design: Difficulty/combinatorial_formula/merit_order_nested_min_max_with_storage_nameplate_sizing
        """
        stack = campus_dispatch_stack(plan_state="OPTIMIZED")

        orders = plan_orders(stack["plan"]["id"])

        assert stack["oil_boiler"]["id"] not in {order["asset_id"] for order in orders}
        assert_plan_metrics(
            stack["plan"],
            plan_state="DRAFT",
            allocated_capacity_kw=2527.20,
            unserved_demand_kw=0.00,
            total_dispatch_cost=1584.36,
            total_emissions_kg=6123.88,
            reserve_margin_pct=46.41,
            fuel_diversity_hhi=0.5489,
        )

    def test_planning_does_not_draw_down_the_live_state_of_charge(self):
        """Optimisation sizes the store from nameplate and leaves the tank alone.

        PRD: "note carefully that the planning horizon sizes storage from nameplate
        `storage_capacity_kwh`, **not** from the live `state_of_charge_kwh`, which
        is checked only at commitment."

        Design: Difficulty/combinatorial_formula/merit_order_nested_min_max_with_storage_nameplate_sizing
        """
        stack = campus_dispatch_stack(plan_state="OPTIMIZED")

        storage = read_asset(stack["storage"]["id"])

        assert storage["state_of_charge_kwh"] == 4000.0


class TestMinimumStableOutputBoundary:
    """A block exactly on the stability floor runs; one hundredth below does not."""

    def test_a_block_exactly_equal_to_the_stability_floor_does_dispatch(self):
        """The cogeneration unit takes its 552.00 kW remainder at a 552.00 kW floor.

        PRD: "If the block is strictly less than the asset's
        `min_stable_output_kw`, the asset is passed over as unable to run stably —
        a block exactly equal to `min_stable_output_kw` does dispatch."

        Design: Difficulty/boundary_precision_check/min_stable_output_exact_equality_dispatches_while_one_cent_above_skips
        """
        stack = industrial_boundary_stack()
        plan = plan_in_state("OPTIMIZED", stack["loop"]["id"], stack["forecast"]["id"])

        orders = plan_orders(plan["id"])

        assert len(orders) == 3, f"expected three dispatch orders, got {len(orders)}"
        assert_dispatch_order(
            orders[2],
            asset_id=stack["exactly_at_remainder"]["id"],
            merit_rank=3,
            allocated_kw=552.00,
            block_energy_mwh=13.248,
            order_cost=529.92,
            order_emissions_kg=132.48,
        )

    def test_a_floor_one_hundredth_above_the_remainder_is_passed_over(self):
        """The cheaper 552.01 kW floor loses its turn and consumes no rank.

        PRD: "Two skip conditions then apply, and neither consumes a rank."

        Design: Difficulty/boundary_precision_check/min_stable_output_exact_equality_dispatches_while_one_cent_above_skips
        """
        stack = industrial_boundary_stack()
        plan = plan_in_state("OPTIMIZED", stack["loop"]["id"], stack["forecast"]["id"])

        orders = plan_orders(plan["id"])

        assert stack["just_above_remainder"]["id"] not in {o["asset_id"] for o in orders}
        assert [order["merit_rank"] for order in orders] == [1, 2, 3]

    def test_the_two_full_capacity_blocks_lead_the_boundary_case(self):
        """Both 750 kW machines clear first and leave exactly 552.00 kW behind.

        PRD: "Eligible assets are ranked cheapest-first: primarily by
        `marginal_cost_per_mwh` ascending, then — for assets that cost the same to
        run — by `emission_factor_kg_per_mwh` ascending so that the cleaner machine
        leads, and finally by `created_at` ascending to make the ordering total."

        Design: Difficulty/boundary_precision_check/min_stable_output_exact_equality_dispatches_while_one_cent_above_skips
        """
        stack = industrial_boundary_stack()
        plan = plan_in_state("OPTIMIZED", stack["loop"]["id"], stack["forecast"]["id"])

        orders = plan_orders(plan["id"])

        assert_dispatch_order(
            orders[0],
            asset_id=stack["cheapest"]["id"],
            merit_rank=1,
            allocated_kw=750.00,
            block_energy_mwh=18.000,
            order_cost=540.00,
            order_emissions_kg=3960.00,
        )
        assert_dispatch_order(
            orders[1],
            asset_id=stack["second"]["id"],
            merit_rank=2,
            allocated_kw=750.00,
            block_energy_mwh=18.000,
            order_cost=576.00,
            order_emissions_kg=540.00,
        )

    def test_the_skipped_machine_still_counts_toward_the_reserve_and_not_the_index(self):
        """Reserve is measured over the eligible set; concentration over the dispatched.

        PRD: "Immediately after the waterfall, and in the same optimisation run,
        two resilience metrics are computed over the *same* eligible asset set —
        not over the dispatched subset."

        Design: Difficulty/boundary_precision_check/min_stable_output_exact_equality_dispatches_while_one_cent_above_skips
        """
        stack = industrial_boundary_stack()

        plan = plan_in_state("OPTIMIZED", stack["loop"]["id"], stack["forecast"]["id"])

        assert_plan_metrics(
            plan,
            plan_state="DRAFT",
            allocated_capacity_kw=2052.00,
            unserved_demand_kw=0.00,
            total_dispatch_cost=1645.92,
            total_emissions_kg=4632.48,
            reserve_margin_pct=12.09,
            fuel_diversity_hhi=0.3395,
        )
