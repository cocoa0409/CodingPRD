"""Composed money formulas: the priced ladder, the per-line fee, the waterfall.

Each formula here fixes not only the arithmetic but the *order* of its steps —
where the rounding lands, which pool the holdback ladder is keyed on, and which
of the two prices wins the min-then-clamp — so re-ordering the steps produces a
different, wrong number.
"""

import pytest

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import TIER_2
from test_helpers.fixtures import (
    countersign_commitment,
    create_active_contract,
    create_commitment,
    create_distribution,
    create_item,
    create_local_exception,
    create_member,
    create_tier_activation,
    distribute_distribution,
    read_distribution,
    read_member,
    set_clock,
)


@pytest.fixture
def top_tier_two_item_setup(api):
    """A TIER_2 commitment against two items: 10000 / floor 8200 and 10010 / floor 0."""
    set_clock(api)
    contract = create_active_contract(api)
    item_floored = create_item(api, contract["id"])
    item_rounding = create_item(
        api,
        contract["id"],
        vendor_item_number="V-2",
        item_description="Suture 4-0 absorbable",
        base_price_cents=10010,
        floor_price_cents=0,
    )
    member = create_member(
        api,
        item_master=[
            f.item_master_row("MI-1"),
            f.item_master_row("MI-2", "Suture 4-0"),
        ],
    )
    commitment = create_commitment(
        api,
        member["id"],
        contract["id"],
        elected_tier_code=TIER_2,
        committed_volume_units=5000,
    )
    commitment = countersign_commitment(api, commitment["id"], member["id"])
    return {
        "contract": contract,
        "item_floored": item_floored,
        "item_rounding": item_rounding,
        "member": member,
        "commitment": commitment,
    }


class TestPriceDerivation:
    """Tier discount, then the local-exception ceiling, then the floor clamp."""

    def test_tier_price_discounts_the_base_price_at_the_commitments_tier(
        self, api, top_tier_two_item_setup
    ):
        """PRD §3.6: "Take 10000 basis points, subtract the tier's `discount_bps`,
        multiply the base price by that difference, divide by 10000, and round the
        result half up to a whole number of cents."
        PRD §3.6: "Worked over a `base_price_cents` of 10000 against a ladder whose
        rungs carry 0, 800 and 1500 basis points of discount, the tier prices are
        10000, 9200 and 8500 cents respectively; over a `base_price_cents` of 10010
        at 1500 basis points the exact result is 8508.5 cents, which rounds half up
        to 8509."
        PRD §3.6: "The server then pins `tier_code_at_activation`: the commitment's
        `current_tier_code` if it has one, or the contract's `default_tier_code` when
        `current_tier_code` is still null — which is the case for any commitment
        whose letter has not yet been countersigned."

        Design: Difficulty/combinatorial_formula/tier_discount_local_exception_and_floor_clamp_interaction
        """
        setup = top_tier_two_item_setup

        tier_price = create_tier_activation(
            api, setup["commitment"]["id"], setup["item_floored"]["id"]
        )

        assert tier_price["tier_code_at_activation"] == TIER_2
        assert tier_price["computed_price_cents"] == 8500
        assert tier_price["price_clamped"] is False

    def test_local_exception_below_the_floor_is_clamped_to_the_floor(
        self, api, top_tier_two_item_setup
    ):
        """PRD §3.6: "If the candidate price from step 3 is strictly below the item's
        `floor_price_cents`, then `computed_price_cents` becomes the floor price and
        `price_clamped` is set to true."
        PRD §3.6: "a requested 8000 cents against a 1500-basis-point tier price of
        8500 with a floor of 8200 yields a candidate of 8000, which is below the
        floor, so `computed_price_cents` becomes 8200 and `price_clamped` is true."

        Design: Difficulty/combinatorial_formula/tier_discount_local_exception_and_floor_clamp_interaction
        """
        setup = top_tier_two_item_setup

        exception = create_local_exception(
            api,
            setup["commitment"]["id"],
            setup["member"]["id"],
            setup["item_floored"]["id"],
            8000,
            stage="DRAFT",
        )

        assert exception["requested_price_cents"] == 8000
        assert exception["computed_price_cents"] == 8200
        assert exception["price_clamped"] is True

    def test_tier_price_rounds_the_discount_half_up_once(
        self, api, top_tier_two_item_setup
    ):
        """PRD §2.5: "Every division in this specification is performed in exact
        decimal arithmetic and rounded **half up** — a value exactly at the midpoint
        rounds away from zero, so 8508.5 cents becomes 8509 cents and 7.0050 becomes
        7.01."
        PRD §3.6: "The rounding boundary is fixed and singular: the only rounding in
        this derivation happens at step 2."

        Design: Difficulty/combinatorial_formula/tier_discount_local_exception_and_floor_clamp_interaction
        """
        setup = top_tier_two_item_setup

        tier_price = create_tier_activation(
            api, setup["commitment"]["id"], setup["item_rounding"]["id"]
        )

        assert tier_price["computed_price_cents"] == 8509
        assert tier_price["price_clamped"] is False

    def test_local_exception_above_the_tier_price_is_ceilinged_not_rejected(
        self, api, top_tier_two_item_setup
    ):
        """PRD §3.6: "When `activation_type` is `LOCAL_EXCEPTION`, the candidate
        price is the **lesser** of the activation's `requested_price_cents` and the
        tier price from step 2 — a local exception may only ever move *down* from the
        tier price, and asking for more than the tier price is silently ceilinged
        rather than rejected."
        PRD §3.6: "Steps 3 and 4 compare and select among values that are already
        whole cents, so a discount is never rounded twice and the floor is never
        crossed by a rounding artifact."

        Design: Difficulty/combinatorial_formula/tier_discount_local_exception_and_floor_clamp_interaction
        """
        setup = top_tier_two_item_setup

        exception = create_local_exception(
            api,
            setup["commitment"]["id"],
            setup["member"]["id"],
            setup["item_rounding"]["id"],
            9000,
            stage="DRAFT",
        )

        assert exception["requested_price_cents"] == 9000
        assert exception["computed_price_cents"] == 8509
        assert exception["price_clamped"] is False


class TestAdminFeeAccrual:
    """The administrative fee is rounded per purchase line, then summed."""

    def test_accrual_rounds_each_line_before_summing_them(self, api, per_line_fee_setup):
        """PRD §3.9: "The lines are visited in order of `purchase_date` ascending and
        then `created_at` ascending, and each one's fee is `extended_cost_cents`
        multiplied by the contract's `admin_fee_bps`, divided by 10000, rounded half
        up to a whole cent."
        PRD §3.9: "The rounding happens per line and only per line — never on the
        summed spend — and the difference is real: two lines of 1150 cents at 300
        basis points each yield 34.5 cents, rounded half up to 35, for a total of 70
        cents, whereas rounding the aggregate would give 2300 times 300 divided by
        10000, or 69 cents."

        Design: Difficulty/combinatorial_formula/admin_fee_rounded_per_line_before_summing
        """
        distribution = create_distribution(api, per_line_fee_setup["contract"]["id"])

        assert distribution["accrued_fee_cents"] == 70
        assert distribution["accrued_fee_cents"] != 69

    def test_a_new_distribution_holds_only_its_accrual(self, api, per_line_fee_setup):
        """PRD §3.9: "The new row is created in `ACCRUED` status with
        `collected_fee_cents` at 0, `basis` null, `holdback_bps_applied`,
        `holdback_cents`, `gross_pool_cents`, `net_pool_cents`, `member_pool_cents`,
        `member_share_total_cents`, `undistributed_cents` and `gpo_retained_cents`
        all at 0, `member_shares` an empty array, and `reverse_note` null."
        PRD §3.9: "`accrued_fee_cents` is computed at the moment of creation and is
        never recomputed by any later transition."

        Design: Difficulty/combinatorial_formula/admin_fee_rounded_per_line_before_summing
        """
        distribution = create_distribution(api, per_line_fee_setup["contract"]["id"])

        assert distribution["status"] == "ACCRUED"
        assert distribution["accrued_fee_cents"] == 70
        assert distribution["collected_fee_cents"] == 0
        assert distribution["basis"] is None
        assert distribution["gross_pool_cents"] == 0
        assert distribution["holdback_bps_applied"] == 0
        assert distribution["holdback_cents"] == 0
        assert distribution["net_pool_cents"] == 0
        assert distribution["member_pool_cents"] == 0
        assert distribution["member_share_total_cents"] == 0
        assert distribution["undistributed_cents"] == 0
        assert distribution["gpo_retained_cents"] == 0
        assert distribution["member_shares"] == []
        assert distribution["reverse_note"] is None


class TestHoldbackWaterfall:
    """The ladder is keyed on the gross pool, and the remainder cent is deterministic."""

    def test_holdback_rung_is_selected_from_the_gross_pool(
        self, api, holdback_two_member_setup
    ):
        """PRD §3.9: "The server takes the ladder entry with the greatest
        `min_gross_pool_cents` that is less than or equal to `gross_pool_cents` and
        writes its `holdback_bps` into `holdback_bps_applied`; if no entry qualifies,
        `holdback_bps_applied` is 0."
        PRD §3.9: "With a holdback ladder of one entry at a 0 minimum and 0 basis
        points and a second at a 100,000-cent minimum and 250 basis points, and a
        `member_share_bps` of 6000, a gross pool of 100,200 cents selects the
        250-basis-point rung, giving a `holdback_cents` of 2505, a `net_pool_cents`
        of 97,695 and a `member_pool_cents` of 58,617."
        PRD §3.9: "Keying on the net pool instead would look up 97,695, fall to the
        0-basis-point rung, hold back nothing, and hand the members 60,120 — the
        holdback would have erased itself by shrinking the pool below its own
        threshold."

        Design: Difficulty/combinatorial_formula/holdback_ladder_keyed_on_gross_pool_before_member_share
        """
        distribution_id = holdback_two_member_setup["distribution"]["id"]
        assert holdback_two_member_setup["distribution"]["accrued_fee_cents"] == 199500

        distribute_distribution(api, distribution_id)

        settled = read_distribution(api, distribution_id)
        assert settled["basis"] == "COLLECTED"
        assert settled["gross_pool_cents"] == 100200
        assert settled["holdback_bps_applied"] == 250
        assert settled["holdback_cents"] == 2505
        assert settled["net_pool_cents"] == 97695
        assert settled["member_pool_cents"] == 58617
        assert settled["member_pool_cents"] != 60120

    def test_member_pool_remainder_cent_goes_to_the_largest_fraction(
        self, api, holdback_two_member_setup
    ):
        """PRD §3.9: "Each exact share is **floored** to a whole cent — floored, not
        rounded — and the shortfall, which is `member_pool_cents` minus the sum of
        the floors and is always strictly less than the number of eligible members,
        is then handed out one cent at a time: the member with the largest fractional
        part gets the first cent, the next largest the next, and ties are broken by
        the member's `created_at` ascending — never by identifier."
        PRD §3.9: "Worked through: a `member_pool_cents` of 58,617 split between
        weights of 4,750,000 and 1,900,000, a total weight of 6,650,000, gives exact
        shares of 41,869.28… and 16,747.71…; the floors are 41,869 and 16,747,
        summing to 58,616, one cent short; the larger fractional part is the second
        member's .71 against the first member's .28, so the remainder cent goes there
        and the final shares are 41,869 and 16,748, summing to exactly 58,617."
        PRD §3.9: "The array is ordered by `share_cents` descending, then by the
        member's `created_at` ascending."

        Design: Difficulty/combinatorial_formula/holdback_ladder_keyed_on_gross_pool_before_member_share
        """
        setup = holdback_two_member_setup
        distribution_id = setup["distribution"]["id"]

        distribute_distribution(api, distribution_id)

        settled = read_distribution(api, distribution_id)
        shares = settled["member_shares"]
        assert len(shares) == 2
        assert shares[0]["member_id"] == setup["member_a"]["id"]
        assert shares[0]["share_cents"] == 41869
        assert shares[1]["member_id"] == setup["member_b"]["id"]
        assert shares[1]["share_cents"] == 16748
        a.assert_member_share(settled, setup["member_a"]["id"], 4750000, 41869)
        a.assert_member_share(settled, setup["member_b"]["id"], 1900000, 16748)
        assert settled["member_share_total_cents"] == 58617
        assert settled["undistributed_cents"] == 0
        assert settled["gpo_retained_cents"] == 41583
        a.assert_waterfall_conserved(settled)

    def test_each_eligible_member_is_credited_its_own_share(
        self, api, holdback_two_member_setup
    ):
        """PRD §3.9: "Every eligible member's `fee_credit_balance_cents` is then
        credited by that member's `share_cents`, incrementing each member's `version`
        by one, the distribution's `status` becomes `DISTRIBUTED`, and its `version`
        increments by one."

        Design: Difficulty/combinatorial_formula/holdback_ladder_keyed_on_gross_pool_before_member_share
        """
        setup = holdback_two_member_setup

        distribute_distribution(api, setup["distribution"]["id"])

        assert read_member(api, setup["member_a"]["id"])["fee_credit_balance_cents"] == 41869
        assert read_member(api, setup["member_b"]["id"])["fee_credit_balance_cents"] == 16748
