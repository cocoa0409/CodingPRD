"""
The forward-looking break-even read.

Turning a target adjusted gross back into a gross is circular, so the answer is
checked both against its published value and against the cent below it.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    GM_HEADERS,
    PRODUCER_HEADERS,
    ApiClient,
    fixtures,
    round_half_up,
)


def _adjusted_gross_at(gross_cents: int) -> int:
    """Gross less its own 5% variable cost, rounded to whole cents."""
    return gross_cents - round_half_up(gross_cents, 0.05)


class TestBreakEvenWithAGuaranteeFloor:
    """The aggregate guarantee floor raises the gross the show has to take."""

    def test_break_even_gross_clears_the_floor_by_exactly_one_cent(
        self, api: ApiClient
    ):
        """A 32,000,000 running cost plus an 800,000 floor plus a cent solves to 34,526,317.

        "Break-even is defined as the smallest weekly gross whose weekly
        operating profit is *strictly* positive, and under the pool structure
        profit is positive exactly when the royalty base clears the guarantee
        floor — so `target_adjusted_gross_cents` is the operating budget's
        `weekly_fixed_running_cost_cents`, plus
        `royalty_min_guarantee_floor_cents`, plus one further cent."

        Design: Difficulty/combinatorial_formula/break_even_circular_gross_solve_with_pool_floor
        """
        world = fixtures.ledger_world(api, pool_basis=True)

        analysis = get_success_data(
            api.get_break_even_analysis(world.production_id, GM_HEADERS), 200
        )

        assert analysis["production_id"] == world.production_id
        assert analysis["operating_budget_id"] == world.operating_budget_id
        # 400,000 + 250,000 + 150,000 across the three active participants.
        assert analysis["royalty_min_guarantee_floor_cents"] == 800_000
        assert analysis["target_adjusted_gross_cents"] == 32_800_001
        assert analysis["break_even_gross_cents"] == 34_526_317
        assert analysis["break_even_paid_capacity_pct"] == 0.1807
        # 1200 seats at 19,900 cents across the budgeted eight performances.
        assert analysis["capacity_gross_projection_cents"] == 191_040_000

    def test_the_published_gross_is_the_smallest_one_that_works(self, api: ApiClient):
        """One cent lower leaves the adjusted gross a cent short of the target.

        "Then walk up: while the candidate less its own variable cost, rounded
        half up to whole cents, is less than `target_adjusted_gross_cents`,
        increase the candidate by one cent."

        Design: Difficulty/combinatorial_formula/break_even_circular_gross_solve_with_pool_floor
        """
        world = fixtures.ledger_world(api, pool_basis=True)

        analysis = get_success_data(
            api.get_break_even_analysis(world.production_id, GM_HEADERS), 200
        )
        answer = analysis["break_even_gross_cents"]
        target = analysis["target_adjusted_gross_cents"]

        assert _adjusted_gross_at(answer) >= target
        assert _adjusted_gross_at(answer - 1) < target
        assert _adjusted_gross_at(answer) == 32_800_001
        assert _adjusted_gross_at(answer - 1) == 32_800_000
        # No week has been certified, so there is no realised run rate to project.
        assert analysis["weeks_to_recoup_at_last_certified_run_rate"] is None


class TestBreakEvenWithoutAGuaranteeFloor:
    """Terminating every participation removes the floor and moves the answer."""

    def test_terminating_every_participation_drops_the_floor_to_zero(
        self, api: ApiClient
    ):
        """With no ACTIVE points-holding participant the floor is 0 and the target 32,000,001.

        "`royalty_min_guarantee_floor_cents` is the sum of
        `min_guarantee_cents` over the production's participations that are
        `ACTIVE` and hold at least 1 `pool_point`; an empty set gives a floor of
        0."

        Design: Difficulty/boundary_precision_check/break_even_shifts_when_pool_floor_removed_by_terminating_participants
        """
        world = fixtures.ledger_world(api, pool_basis=True)

        before = get_success_data(
            api.get_break_even_analysis(world.production_id, GM_HEADERS), 200
        )
        assert before["royalty_min_guarantee_floor_cents"] == 800_000
        assert before["target_adjusted_gross_cents"] == 32_800_001
        assert before["break_even_gross_cents"] == 34_526_317
        assert before["break_even_paid_capacity_pct"] == 0.1807

        for participant_id in world.participant_ids:
            get_success_data(
                api.terminate_royalty_participant(participant_id, PRODUCER_HEADERS), 200
            )

        after = get_success_data(
            api.get_break_even_analysis(world.production_id, GM_HEADERS), 200
        )
        assert after["royalty_min_guarantee_floor_cents"] == 0
        assert after["target_adjusted_gross_cents"] == 32_000_001
        assert after["break_even_gross_cents"] == 33_684_212
        assert after["break_even_paid_capacity_pct"] == 0.1763
        assert after["weeks_to_recoup_at_last_certified_run_rate"] is None
        assert world.production()["total_pool_points"] == 0

    def test_the_floorless_answer_is_also_minimal_to_the_cent(self, api: ApiClient):
        """33,684,211 yields 32,000,000 of adjusted gross, one cent under the target.

        "Because the quantity \"gross less its rounded variable cost\" never
        decreases as gross increases, both walks are monotone and both
        terminate; neither needs more than one hundred steps from the seed."

        Design: Difficulty/boundary_precision_check/break_even_shifts_when_pool_floor_removed_by_terminating_participants
        """
        world = fixtures.ledger_world(api, pool_basis=True)
        for participant_id in world.participant_ids:
            get_success_data(
                api.terminate_royalty_participant(participant_id, PRODUCER_HEADERS), 200
            )

        analysis = get_success_data(
            api.get_break_even_analysis(world.production_id, GM_HEADERS), 200
        )
        answer = analysis["break_even_gross_cents"]

        assert answer == 33_684_212
        assert _adjusted_gross_at(answer) == 32_000_001
        assert _adjusted_gross_at(answer - 1) == 32_000_000
        assert _adjusted_gross_at(answer - 1) < analysis["target_adjusted_gross_cents"]
        assert analysis["capacity_gross_projection_cents"] == 191_040_000
