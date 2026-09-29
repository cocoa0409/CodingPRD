"""
The pool charge's two clamps, and the pinned split of the pool into allocations.

Both concerns need a converted production with three participants whose points
are 4, 3 and 2 and whose aggregate guarantee floor is 800,000 cents.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import (
    COMPTROLLER_HEADERS,
    GM_HEADERS,
    ApiClient,
    World,
    fixtures,
)


def _certify(world: World, **overrides) -> str:
    """Open, submit and certify one week at whatever the clock currently reads."""
    wrap_id = fixtures.new_wrap(world, **overrides)
    fixtures.submit_wrap(world, wrap_id)
    fixtures.certify_wrap(world, wrap_id)
    return wrap_id


def _allocations_by_participant(api: ApiClient, wrap_id: str):
    """The allocation rows a certification produced, keyed by participant."""
    response = api.list_royalty_allocations(COMPTROLLER_HEADERS, {"wrap_id": wrap_id})
    rows, meta = validate_paginated(response)
    return {row["royalty_participant_id"]: row for row in rows}, meta


class TestPoolChargeClampOrdering:
    """The guarantee floor lifts the charge, then the base caps it."""

    def test_guarantee_floor_lifts_a_charge_below_the_aggregate_minimum(
        self, api: ApiClient
    ):
        """A base of 2,000,000 gives 700,000 at 35%, so the 800,000 floor wins.

        "Otherwise `royalty_pool_cents` is computed in three pinned steps: take
        `royalty_base_cents` multiplied by the applicable pool percentage and
        round half up to whole cents; take the greater of that figure and
        `pool_floor_cents`, which is the floor the guarantees impose in
        aggregate; then take the lesser of that result and
        `royalty_base_cents`, which caps the burden so that a week can never
        owe more royalty than it earned in operating profit."

        Design: Difficulty/combinatorial_formula/pool_charge_nested_clamp_floor_then_cap_ordering
        """
        world = fixtures.ledger_world(api, pool_basis=True)
        world.set_clock("2026-09-07")

        wrap_id = _certify(world, running_expenses_cents=59_750_000)
        wrap = get_success_data(api.get_weekly_wrap(wrap_id, GM_HEADERS), 200)

        assert wrap["royalty_base_cents"] == 2_000_000
        assert wrap["royalty_pool_cents"] == 800_000
        assert wrap["weekly_operating_profit_cents"] == 1_200_000
        assert wrap["deferred_royalty_added_cents"] == 0

    def test_royalty_base_caps_a_floor_that_would_exceed_the_week_s_profit(
        self, api: ApiClient
    ):
        """A base of 500,000 cannot owe the 800,000 floor, so the cap pulls it back.

        "Whichever variant applied, `weekly_operating_profit_cents` is the
        wrap's `royalty_base_cents` less its `royalty_pool_cents`."

        Design: Difficulty/combinatorial_formula/pool_charge_nested_clamp_floor_then_cap_ordering
        """
        world = fixtures.ledger_world(api, pool_basis=True)
        world.set_clock("2026-09-07")
        _certify(world, running_expenses_cents=59_750_000)

        world.set_clock("2026-09-14")
        capped_id = _certify(
            world, week_ending_date="2026-09-13", running_expenses_cents=61_250_000
        )
        capped = get_success_data(api.get_weekly_wrap(capped_id, GM_HEADERS), 200)

        assert capped["royalty_base_cents"] == 500_000
        assert capped["royalty_pool_cents"] == 500_000
        assert capped["weekly_operating_profit_cents"] == 0
        assert capped["weekly_operating_profit_cents"] >= 0

        production = world.production()
        # 1,200,000 from the floor-bound week plus nothing from the capped one.
        assert production["recouped_amount_cents"] == 1_200_000
        assert production["recoupment_pct"] == 0.0100
        assert production["deferred_royalty_cents"] == 0


class TestPoolSplitResiduePinning:
    """Each share rounds first, then the signed residue lands on one row."""

    def test_positive_residue_lands_on_the_highest_points_participant(
        self, api: ApiClient
    ):
        """9,887,500 over 4/3/2 points leaves +1 cent, which goes to the author.

        "Under the pool variant, reconciliation is required and its order is
        pinned: first compute each participant's raw share as the wrap's
        `royalty_pool_cents` multiplied by that participant's `pool_points`
        divided by the point total, rounding **each participant's share to
        whole cents first**; then subtract the sum of those rounded shares from
        the wrap's `royalty_pool_cents` to get a residue, which may be
        negative; then add that residue to the first participant in the order
        — highest `pool_points`, earliest `created_at` among ties."

        Design: Difficulty/combinatorial_formula/royalty_pool_split_signed_residue_pinning_both_directions
        """
        world = fixtures.ledger_world(api, pool_basis=True)
        world.set_clock("2026-09-07")
        wrap_id = _certify(world)

        author_id, composer_id, director_id = world.participant_ids
        rows, meta = _allocations_by_participant(api, wrap_id)

        assert meta["total_count"] == 3
        # 4,394,444 + 3,295,833 + 2,197,222 is 9,887,499, so +1 is pinned on the
        # participant holding four points.
        assert rows[author_id]["allocated_cents"] == 4_394_445
        assert rows[composer_id]["allocated_cents"] == 3_295_833
        assert rows[director_id]["allocated_cents"] == 2_197_222
        assert sum(row["allocated_cents"] for row in rows.values()) == 9_887_500
        for row in rows.values():
            assert row["status"] == "ALLOCATED"
            assert row["basis"] == "POOL"
            assert row["wrap_id"] == wrap_id

    def test_negative_residue_lands_on_the_same_participant(self, api: ApiClient):
        """A floor-bound pool of 800,000 leaves -1 cent, also taken off the author.

        "Summing exact fractions and rounding once at the end is *not* the
        specified order and will disagree by cents."

        Design: Difficulty/combinatorial_formula/royalty_pool_split_signed_residue_pinning_both_directions
        """
        world = fixtures.ledger_world(api, pool_basis=True)
        world.set_clock("2026-09-07")
        _certify(world)

        world.set_clock("2026-09-14")
        floor_wrap_id = _certify(
            world, week_ending_date="2026-09-13", running_expenses_cents=59_750_000
        )

        author_id, composer_id, director_id = world.participant_ids
        rows, meta = _allocations_by_participant(api, floor_wrap_id)

        assert meta["total_count"] == 3
        # 355,556 + 266,667 + 177,778 is 800,001, so -1 is pinned on the author.
        assert rows[author_id]["allocated_cents"] == 355_555
        assert rows[composer_id]["allocated_cents"] == 266_667
        assert rows[director_id]["allocated_cents"] == 177_778
        assert sum(row["allocated_cents"] for row in rows.values()) == 800_000
        assert rows[author_id]["points_at_allocation"] == 4
        assert rows[composer_id]["points_at_allocation"] == 3
        assert rows[director_id]["points_at_allocation"] == 2
        for row in rows.values():
            assert row["status"] == "ALLOCATED"
