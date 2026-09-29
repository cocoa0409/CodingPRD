"""Committed cost tiers at plan time and the channel positioning waterfall.

Both computations combine several stored inputs in a pinned order, so the
observable figures depend on which quantity keys the tier and on when each
rounding and ceiling is applied.
"""

import pytest

from test_helpers import (
    build_allocatable_plant,
    build_assembly_line,
    build_certification_family,
    build_engine_platform,
    build_product_model,
    build_safety_certification,
    build_order_version,
    plan_build_order,
    read_build_order,
    read_engine_unit,
    release_product_model,
    run_allocations,
    assert_build_order_unit_conservation,
)

PRODUCTION_WEEK = "2026-09-14"
WEEK_SPAN = 2


def _plan_ready_model():
    """A released walk-mower model, which is all a plan needs upstream."""
    family = build_certification_family()
    platform = build_engine_platform(family["id"])
    model = build_product_model(platform["id"])
    build_safety_certification(model["id"])
    return release_product_model(model["id"])


def _plan_on_dedicated_line(model_id, line_code, planned_quantity):
    """One order per line, so no other order's weekly load interacts."""
    line = build_assembly_line(
        line_code=line_code, supported_product_lines=["WALK_MOWER"]
    )
    return plan_build_order(
        model_id,
        line["id"],
        season="PRE_SEASON",
        production_week=PRODUCTION_WEEK,
        week_span=WEEK_SPAN,
        planned_quantity=planned_quantity,
    )


class TestCarryCostTierSelection:
    """The weekly carry rate is keyed on the build value alone."""

    def test_small_pre_season_build_carries_at_the_lowest_tier_rate(
        self, canonical_clock
    ):
        """PRD §3.6: "`build_value_cents` is `planned_quantity` multiplied by the model's `standard_cost_cents`."
        PRD §3.6: "The weekly `carry_rate` is then selected **from `build_value_cents` alone**: 0.0040 when the build value is below 5,000,000 cents, 0.0030 when it is below 20,000,000 cents, and 0.0020 otherwise — so the tier ceilings are exclusive at the bottom of the next tier and a build value of exactly 20,000,000 cents lands on the 0.0020 rate."
        PRD §3.6: "`carry_cost_cents` is `build_value_cents` multiplied by `carry_rate` multiplied by `carry_weeks`, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/carry_cost_tier_selection_non_linear_in_quantity
        """
        model = _plan_ready_model()
        order = _plan_on_dedicated_line(model["id"], "L1", 6)

        assert order["build_value_cents"] == 126000
        assert order["carry_weeks"] == 24
        assert order["carry_rate"] == pytest.approx(0.0040, abs=0.00005)
        assert order["carry_cost_cents"] == 12096
        assert order["total_committed_cents"] == 138096
        assert order["status"] == "PLANNED"
        assert order["allocation_status"] == "UNALLOCATED"
        assert order["staged_quantity"] == 0

    def test_carry_cost_per_unit_falls_as_the_build_crosses_the_tier_ceilings(
        self, canonical_clock
    ):
        """PRD §3.6: "The weekly `carry_rate` is then selected **from `build_value_cents` alone**: 0.0040 when the build value is below 5,000,000 cents, 0.0030 when it is below 20,000,000 cents, and 0.0020 otherwise — so the tier ceilings are exclusive at the bottom of the next tier and a build value of exactly 20,000,000 cents lands on the 0.0020 rate."
        PRD §3.6: "`total_committed_cents` is `build_value_cents` plus `carry_cost_cents`."

        Design: Difficulty/combinatorial_formula/carry_cost_tier_selection_non_linear_in_quantity
        """
        model = _plan_ready_model()
        medium = _plan_on_dedicated_line(model["id"], "L-CARRY-M", 600)
        large = _plan_on_dedicated_line(model["id"], "L-CARRY-L", 1000)

        assert medium["build_value_cents"] == 12600000
        assert medium["carry_rate"] == pytest.approx(0.0030, abs=0.00005)
        assert medium["carry_cost_cents"] == 907200
        assert medium["total_committed_cents"] == 13507200

        assert large["build_value_cents"] == 21000000
        assert large["carry_rate"] == pytest.approx(0.0020, abs=0.00005)
        assert large["carry_cost_cents"] == 1008000
        assert large["total_committed_cents"] == 22008000

        # 1512 cents a unit at 600 units, 1008 cents a unit at 1000 units.
        assert medium["carry_cost_cents"] / 600 > large["carry_cost_cents"] / 1000

    def test_total_committed_cost_never_reselects_the_carry_tier(
        self, canonical_clock
    ):
        """PRD §3.6: "That last sum is what the plant commits, but it never feeds back into tier selection: the carry rate is chosen from the build value and only from the build value, however large the resulting total becomes."
        PRD §3.6: "`carry_cost_cents` is `build_value_cents` multiplied by `carry_rate` multiplied by `carry_weeks`, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/carry_cost_total_committed_never_reselects_tier
        """
        model = _plan_ready_model()
        order = _plan_on_dedicated_line(model["id"], "L-CARRY-C", 950)

        assert order["build_value_cents"] == 19950000
        assert order["carry_weeks"] == 24
        assert order["carry_rate"] == pytest.approx(0.0030, abs=0.00005)
        assert order["carry_cost_cents"] == 1436400
        assert order["total_committed_cents"] == 21386400
        assert order["total_committed_cents"] > 20000000

    def test_carry_rate_stays_on_the_build_value_tier_when_the_total_crosses_it(
        self, canonical_clock
    ):
        """PRD §3.6: "The weekly `carry_rate` is then selected **from `build_value_cents` alone**: 0.0040 when the build value is below 5,000,000 cents, 0.0030 when it is below 20,000,000 cents, and 0.0020 otherwise — so the tier ceilings are exclusive at the bottom of the next tier and a build value of exactly 20,000,000 cents lands on the 0.0020 rate."
        PRD §3.6: "That last sum is what the plant commits, but it never feeds back into tier selection: the carry rate is chosen from the build value and only from the build value, however large the resulting total becomes."

        Design: Difficulty/combinatorial_formula/carry_cost_total_committed_never_reselects_tier
        """
        model = _plan_ready_model()
        below_ceiling = _plan_on_dedicated_line(model["id"], "L-CARRY-C", 950)
        above_ceiling = _plan_on_dedicated_line(model["id"], "L-CARRY-L", 1000)

        # A total above the ceiling keeps the middle rate; only a build value
        # above the ceiling earns the low rate.
        assert below_ceiling["total_committed_cents"] > 20000000
        assert below_ceiling["carry_rate"] == pytest.approx(0.0030, abs=0.00005)
        assert below_ceiling["carry_cost_cents"] != 957600
        assert above_ceiling["build_value_cents"] >= 20000000
        assert above_ceiling["carry_rate"] == pytest.approx(0.0020, abs=0.00005)


class TestChannelAllocationWaterfall:
    """The released pool is split floor first, then the remainder, then the caps."""

    def test_waterfall_floors_both_shares_and_gives_the_remainder_to_dealer(
        self, canonical_clock
    ):
        """PRD §3.8: "The raw dealer share is the pool multiplied by the model's `dealer_share_pct`, and the raw mass-retail share is the pool multiplied by one minus `dealer_share_pct`."
        PRD §3.8: "Both raw shares are rounded **down** to whole units."
        PRD §3.8: "When it is 1, that single unit goes to whichever bucket had the larger fractional part, and when the two fractional parts are equal the unit goes to the **dealer** bucket."

        Design: Difficulty/combinatorial_formula/channel_waterfall_floor_then_remainder_rounding_order
        """
        scenario = build_allocatable_plant(released_units=3)
        order = scenario.build_order
        assert order["built_quantity"] == 3
        assert order["staged_quantity"] == 0

        allocated = run_allocations(order["id"])

        # A pool of 3 at a 0.55 dealer share: 1.65 and 1.35 both floor to 1,
        # and the stranded unit follows the larger fractional part.
        assert allocated["allocated_dealer_units"] == 2
        assert allocated["allocated_mass_retail_units"] == 1
        assert allocated["unallocated_units"] == 0
        assert allocated["allocation_status"] == "ALLOCATED"
        assert_build_order_unit_conservation(allocated)

    def test_allocation_run_stamps_the_clock_and_advances_the_order_version(
        self, canonical_clock
    ):
        """PRD §3.8: "The results are written as `allocated_dealer_units`, `allocated_mass_retail_units` and `unallocated_units`, `allocation_status` becomes `ALLOCATED`, `allocation_run_at` is stamped from the clock, and the order's `version` increments by 1."
        PRD §3.7: "When the release brings `built_quantity` up to the order's `planned_quantity`, the order transitions `IN_PRODUCTION → COMPLETED` in the same request; a `COMPLETED` order accepts no further units, though allocation runs remain permitted on it."

        Design: Difficulty/combinatorial_formula/channel_waterfall_floor_then_remainder_rounding_order
        """
        scenario = build_allocatable_plant(released_units=3)
        order_id = scenario.build_order["id"]
        version_before = build_order_version(order_id)

        allocated = run_allocations(order_id, expected_version=version_before)

        assert allocated["version"] == version_before + 1
        assert allocated["allocation_run_at"].startswith("2026-08-03T08:00:00")
        assert allocated["status"] == "IN_PRODUCTION"

        stored = read_build_order(order_id)
        assert stored["allocated_dealer_units"] == 2
        assert stored["allocated_mass_retail_units"] == 1
        assert stored["allocation_status"] == "ALLOCATED"

    def test_released_units_carry_the_standard_hot_test_allowance(
        self, canonical_clock
    ):
        """PRD §3.7: "For an ordinary unit the factor is 1.10, allowing a ten percent production allowance above the certified value."
        PRD §3.7: "Releasing a unit to finished goods requires `build_state` `HOT_TESTED`, else `ERR_UNIT_STATE_INVALID`; `conformance_state` `CONFORMING`, else `ERR_UNIT_NONCONFORMING`; and a parent order whose status is `RELEASED` or `IN_PRODUCTION`."

        Design: Difficulty/combinatorial_formula/channel_waterfall_floor_then_remainder_rounding_order
        """
        scenario = build_allocatable_plant(released_units=3)
        for staged in scenario.units:
            unit = read_engine_unit(staged["id"])
            assert unit["build_state"] == "RELEASED"
            assert unit["conformance_state"] == "CONFORMING"
            assert unit["hot_test_emission_threshold"] == pytest.approx(5.63, abs=0.005)
