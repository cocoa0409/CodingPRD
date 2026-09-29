"""The two order-sensitive money formulas: the equity gross-up and the split.

Both are combinatorial in the sense that the same inputs produce a different
answer if the declared steps are reordered or if two roundings are collapsed
into one, so each test pins the figure the declared order forces.
"""

import pytest

from test_helpers import (
    CANONICAL_ALLOCATION,
    CANONICAL_CAPITAL_STACK,
    CANONICAL_DISTRIBUTION,
    TRUSTEE,
    api_client,
    assert_allocation_sum_equals,
    assert_distribution_allocation,
    declare_offering_effective,
    get_success_data,
    setup_offering_under_review,
    setup_paid_distribution,
    validate_paginated,
    validate_success,
)


class TestOfferingCapitalStackGrossUp:
    def test_declaring_effective_pins_the_reserve_target_and_load_residual(self):
        """The reserve enters the need before the gross-up, and the load is the residual.

        PRD: "The fifth step is the one implementers get wrong: the sponsor load
        is the residual implied by the gross-up, never `load_pct` multiplied by
        `target_equity_cents`."

        Design: Difficulty/combinatorial_formula/offering_capital_stack_grossup_evaluation_order
        """
        deal = setup_offering_under_review()

        offering = declare_offering_effective(deal["offering"]["id"], 1)

        assert offering["status"] == "EFFECTIVE"
        assert offering["initial_reserve_cents"] == (
            CANONICAL_CAPITAL_STACK["initial_reserve_cents"]
        )
        assert offering["target_equity_cents"] == (
            CANONICAL_CAPITAL_STACK["target_equity_cents"]
        )
        assert offering["sponsor_load_cents"] == (
            CANONICAL_CAPITAL_STACK["sponsor_load_cents"]
        )
        # Grossing up the net acquisition figure first and adding the reserve
        # afterwards would have produced 596,978,022 cents instead.
        assert offering["target_equity_cents"] != 596_978_022

    def test_capital_stack_read_reports_every_step_of_the_pinned_order(self):
        """The computed read exposes the intermediate figures of the five steps.

        PRD: "The base need is that net acquisition figure plus
        `initial_reserve_cents`."

        Design: Difficulty/combinatorial_formula/offering_capital_stack_grossup_evaluation_order
        """
        deal = setup_offering_under_review()
        offering = declare_offering_effective(deal["offering"]["id"], 1)

        stack = get_success_data(api_client.get_capital_stack(offering["id"], TRUSTEE))

        assert stack["net_acquisition_cents"] == (
            CANONICAL_CAPITAL_STACK["net_acquisition_cents"]
        )
        assert stack["base_need_cents"] == CANONICAL_CAPITAL_STACK["base_need_cents"]
        assert stack["initial_reserve_cents"] == (
            CANONICAL_CAPITAL_STACK["initial_reserve_cents"]
        )
        assert stack["unit_capacity_cents"] == (
            CANONICAL_CAPITAL_STACK["unit_capacity_cents"]
        )
        assert stack["target_equity_cents"] == (
            CANONICAL_CAPITAL_STACK["target_equity_cents"]
        )
        assert (
            stack["target_equity_cents"] - stack["base_need_cents"]
            == stack["sponsor_load_cents"]
        )

    def test_load_basis_point_conversion_and_capacity_test_hold_together(self):
        """Nine percent becomes 900 basis points and 620 units can carry the target.

        PRD: "The load percentage is converted to whole basis points by
        multiplying `load_pct` by ten thousand and rounding half up."

        Design: Difficulty/combinatorial_formula/offering_capital_stack_grossup_evaluation_order
        """
        deal = setup_offering_under_review()
        offering = declare_offering_effective(deal["offering"]["id"], 1)

        base_need = CANONICAL_CAPITAL_STACK["base_need_cents"]
        # base_need * 10000 / (10000 - 900), rounded up when inexact.
        expected = -(-(base_need * 10_000) // (10_000 - 900))
        assert offering["target_equity_cents"] == expected

        stack = get_success_data(api_client.get_capital_stack(offering["id"], TRUSTEE))
        assert stack["unit_capacity_cents"] >= stack["target_equity_cents"]
        assert stack["equity_committed_cents"] == 0
        assert stack["equity_remaining_cents"] == offering["target_equity_cents"]


class TestDistributionAllocationRoundThenSweep:
    def test_each_share_is_rounded_before_the_residual_is_swept(self):
        """Two equal .5 shares round up, then a one-cent residual is taken back.

        PRD: "`allocated_cents` is `raw_share_cents` rounded half up to whole
        cents."

        Design: Difficulty/combinatorial_formula/distribution_allocation_round_then_residual_sweep
        """
        deal = setup_paid_distribution()
        rows = deal["allocations"]
        by_subscription = {row["subscription_id"]: row for row in rows}

        row_a = by_subscription[deal["subscription_a"]["id"]]
        row_b = by_subscription[deal["subscription_b"]["id"]]

        assert row_a["units"] == 300
        assert row_b["units"] == 300
        assert row_a["raw_share_cents"] == pytest.approx(
            CANONICAL_ALLOCATION["raw_share_cents"], abs=0.01
        )
        assert row_b["raw_share_cents"] == pytest.approx(
            CANONICAL_ALLOCATION["raw_share_cents"], abs=0.01
        )
        assert row_a["allocated_cents"] == (
            CANONICAL_ALLOCATION["subscription_a_allocated_cents"]
        )
        assert row_a["residual_adjustment_cents"] == (
            CANONICAL_ALLOCATION["subscription_a_residual_adjustment_cents"]
        )
        assert row_b["allocated_cents"] == (
            CANONICAL_ALLOCATION["subscription_b_allocated_cents"]
        )
        assert row_b["residual_adjustment_cents"] == (
            CANONICAL_ALLOCATION["subscription_b_residual_adjustment_cents"]
        )

    def test_the_negative_residual_lands_on_the_earliest_closing(self):
        """Equal fractional parts are broken by closing ordinal, never by id.

        PRD: "Each row's `residual_adjustment_cents` records the plus one, minus
        one or zero that was applied to it."

        Design: Difficulty/combinatorial_formula/distribution_allocation_round_then_residual_sweep
        """
        deal = setup_paid_distribution()
        assert deal["subscription_a"]["closing_sequence_no"] == 1
        assert deal["subscription_b"]["closing_sequence_no"] == 2

        by_subscription = {row["subscription_id"]: row for row in deal["allocations"]}
        row_a = by_subscription[deal["subscription_a"]["id"]]
        row_b = by_subscription[deal["subscription_b"]["id"]]

        assert row_a["residual_adjustment_cents"] == -1
        assert row_b["residual_adjustment_cents"] == 0

    def test_the_allocated_cents_sum_equals_the_final_amount_exactly(self):
        """The sweep exists to make the split total the distributed amount.

        PRD: "The invariant that must hold afterwards is that the sum of
        `allocated_cents` across every row equals the amount exactly."

        Design: Difficulty/combinatorial_formula/distribution_allocation_round_then_residual_sweep
        """
        deal = setup_paid_distribution()
        final_amount = deal["distribution"]["final_amount_cents"]
        assert final_amount == CANONICAL_DISTRIBUTION["final_amount_cents"]

        response = api_client.list_distribution_allocations(
            TRUSTEE, params={"distribution_id": deal["distribution"]["id"], "limit": 100}
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 2
        for row in rows:
            assert_distribution_allocation(row)
        assert_allocation_sum_equals(rows, final_amount)
        # Summing the raw shares and rounding once would have paid 14,771,302.
        assert sum(row["allocated_cents"] for row in rows) != 14_771_302

    def test_one_allocation_row_is_readable_on_its_own_endpoint(self):
        """Allocation rows are journal rows discoverable through their list.

        PRD: "Each allocation row carries its `distribution_id`, its
        `subscription_id`, its `units`, its `raw_share_cents`, its
        `allocated_cents` and its `residual_adjustment_cents`."

        Design: Difficulty/combinatorial_formula/distribution_allocation_round_then_residual_sweep
        """
        deal = setup_paid_distribution()
        row = deal["allocations"][0]

        response = api_client.get_distribution_allocation(row["id"], TRUSTEE)
        data = validate_success(response)

        assert data["distribution_id"] == deal["distribution"]["id"]
        assert_distribution_allocation(data)
