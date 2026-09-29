"""Two order-sensitive formulas: per-benefit rounding and largest-remainder cost.

Both cases are built so that the forbidden alternative order produces a
different, observably wrong number.
"""

import pytest

from test_helpers import (
    add_partner,
    benefit_payload,
    collaboration_action,
    define_tier,
    enrol_member,
    open_collaboration,
    open_fiscal_period,
    publish_tier,
    read_collaboration,
    read_member,
    read_partner,
    record_contribution,
    register_coverage_area,
    settle_contribution,
)


def _four_benefit_monthly_tier():
    """A MONTHLY tier at 2500 cents carrying annual benefit values of 1000,
    1000, 1000 and 480 cents."""
    return define_tier(
        benefits=[
            benefit_payload("TOTE", "TOTE_BAG", 1000),
            benefit_payload("EVENT", "EVENT_ACCESS", 1000),
            benefit_payload("BOOK", "BOOK", 1000),
            benefit_payload("NEWSLETTER", "NEWSLETTER", 480),
        ],
        tier_code="SUSTAINER",
        name="Monthly Sustainer",
        renewal_cadence="MONTHLY",
        contribution_amount_cents=2500,
        grace_period_days=30,
    )


class TestTierQuidProQuoRoundsEachBenefitFirst:
    """Per-benefit rounding before summing, on a MONTHLY tier."""

    def test_three_thousand_cents_of_annual_benefits_value_at_249_not_250(self):
        """Each 1000-cent annual benefit rounds to 83 on its own, so the three
        substantial benefits sum to 249 and never to the 250 that dividing the
        combined annual total would give.

        PRD: "Rounding per benefit first and summing afterwards is the required
        order and it is not interchangeable with the alternative: three benefits
        worth 1000 cents a year each on a `MONTHLY` tier contribute 83 plus 83
        plus 83, which is 249 cents - not the 250 cents that summing the annual
        values and dividing the total by 12 would produce."

        Design: Difficulty/combinatorial_formula/cf_tier_quid_pro_quo_rounds_each_benefit_before_summing
        """
        tier = _four_benefit_monthly_tier()

        assert tier["insubstantial_threshold_cents"] == 50
        assert tier["quid_pro_quo_per_period_cents"] == 249
        assert tier["quid_pro_quo_per_period_cents"] != 250
        assert tier["insubstantial_benefit_codes"] == ["NEWSLETTER"]
        assert tier["benefit_count"] == 4
        assert tier["status"] == "DRAFT"

        published = publish_tier(tier["id"])
        assert published["status"] == "PUBLISHED"
        assert published["quid_pro_quo_per_period_cents"] == 249

    def test_the_enrolling_contribution_deducts_2251_not_2250(self):
        """The membership contribution copies the tier's frozen 249 and leaves
        2251 deductible, and its settlement activates the member.

        PRD: "A `MEMBERSHIP` contribution takes `quid_pro_quo_cents` from the
        `quid_pro_quo_per_period_cents` of the tier the member references *at the
        moment of evaluation*, and `deductible_cents` is `amount_cents` minus
        that value floored at 0."

        Design: Difficulty/combinatorial_formula/cf_tier_quid_pro_quo_rounds_each_benefit_before_summing
        """
        period = open_fiscal_period()
        tier = _four_benefit_monthly_tier()
        publish_tier(tier["id"])
        member = enrol_member(tier["id"], email="avery@example.org", full_name="Avery Nunez")

        contribution = record_contribution(
            period["id"],
            "MEMBERSHIP",
            2500,
            member_id=member["id"],
            received_date="2026-08-10",
        )
        assert contribution["quid_pro_quo_cents"] == 249
        assert contribution["deductible_cents"] == 2251

        settled = settle_contribution(contribution["id"])
        assert settled["settlement_status"] == "SETTLED"

        activated = read_member(member["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["lifetime_giving_cents"] == 2500
        assert activated["is_major_donor"] is False

    def test_the_benefit_at_forty_cents_a_period_is_the_only_insubstantial_one(self):
        """40 cents a period is at or below the 50-cent threshold while 83 is
        not, so exactly one benefit code is excluded from the quid pro quo.

        PRD: "A benefit is insubstantial when its per-period value is less than
        *or equal to* `insubstantial_threshold_cents`; a benefit sitting exactly
        on the threshold is insubstantial."

        Design: Difficulty/combinatorial_formula/cf_tier_quid_pro_quo_rounds_each_benefit_before_summing
        """
        tier = _four_benefit_monthly_tier()

        assert tier["insubstantial_threshold_cents"] == 50
        assert tier["insubstantial_benefit_codes"] == ["NEWSLETTER"]
        assert tier["quid_pro_quo_per_period_cents"] == 83 + 83 + 83
        assert tier["benefit_count"] == 4


def _setup_three_way_split_collaboration():
    """A DRAFT collaboration costing 100002 cents split 3334/3333/3333 bps
    between the lead and two partners added in a fixed order."""
    period = open_fiscal_period()
    area = register_coverage_area(
        area_code="CLIMATE",
        name="Climate and energy",
        editorial_lead_user_id="user-ed-7",
    )
    collaboration = open_collaboration(
        area["id"],
        period["id"],
        title="Heat island investigation",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-10-01T00:00:00Z",
        total_cost_cents=100002,
        lead_credit_bps=3334,
        lead_cost_share_bps=3334,
    )
    first = add_partner(collaboration["id"], "Delta River Report", 3333, 3333)
    second = add_partner(collaboration["id"], "Harbor Light News", 3333, 3333)
    return {
        "period": period,
        "area": area,
        "collaboration": collaboration,
        "first": first,
        "second": second,
    }


class TestLargestRemainderSplitConservesTotalCost:
    """100002 cents apportioned 3334/3333/3333 basis points."""

    def test_activation_apportions_33341_33331_and_33330(self):
        """The exact shares are 33340.6668, 33330.6666 and 33330.6666, so the
        floors are 33340/33330/33330 with two leftover cents handed to the two
        highest remainders.

        PRD: "Participants are ranked by remainder descending with `created_at`
        ascending as the tie-break, and the first *leftover* ranked participants
        each receive exactly one extra cent."

        Design: Difficulty/combinatorial_formula/cf_collaboration_largest_remainder_split_conserves_total_cost
        """
        ctx = _setup_three_way_split_collaboration()

        activated = collaboration_action(ctx["collaboration"]["id"], "ACTIVATE")
        assert activated["status"] == "ACTIVE"
        assert activated["partner_count"] == 2
        assert activated["lead_cost_cents"] == 33341

        first = read_partner(ctx["first"]["id"])
        second = read_partner(ctx["second"]["id"])
        assert first["cost_owed_cents"] == 33331
        assert second["cost_owed_cents"] == 33330

    def test_the_allocation_sums_to_the_total_that_independent_rounding_overshoots(self):
        """Rounding each share half up on its own would emit 33341 + 33331 +
        33331 = 100003, one cent more than the collaboration costs.

        PRD: "Rounding each share independently with round half up is
        **forbidden**, because independently rounded shares do not sum to the
        total."

        Design: Difficulty/combinatorial_formula/cf_collaboration_largest_remainder_split_conserves_total_cost
        """
        ctx = _setup_three_way_split_collaboration()

        activated = collaboration_action(ctx["collaboration"]["id"], "ACTIVATE")
        first = read_partner(ctx["first"]["id"])
        second = read_partner(ctx["second"]["id"])

        total = (
            activated["lead_cost_cents"]
            + first["cost_owed_cents"]
            + second["cost_owed_cents"]
        )
        assert total == 100002
        assert total == activated["total_cost_cents"]
        assert activated["allocated_cost_cents"] == 100002
        assert total != 100003
        assert activated["syndication_revenue_cents"] == 0

    def test_the_exact_remainder_tie_is_broken_by_creation_order(self):
        """Both partners hold the identical fractional remainder, so the earlier
        row ranks second and takes the cent while the later row ranks third and
        does not.

        PRD: "The participants are the lead, whose share is `lead_cost_share_bps`
        and whose sort key is the collaboration's own `created_at`, followed by
        the `CONFIRMED` partner rows in `created_at` ascending order."

        Design: Difficulty/combinatorial_formula/cf_collaboration_largest_remainder_split_conserves_total_cost
        """
        ctx = _setup_three_way_split_collaboration()

        collaboration_action(ctx["collaboration"]["id"], "ACTIVATE")
        first = read_partner(ctx["first"]["id"])
        second = read_partner(ctx["second"]["id"])

        assert first["remainder_rank"] == 2
        assert second["remainder_rank"] == 3
        assert first["cost_owed_cents"] - second["cost_owed_cents"] == 1
        assert first["credit_share_bps"] == 3333
        assert second["credit_share_bps"] == 3333

    def test_a_draft_collaboration_has_not_yet_apportioned_anything(self):
        """Before activation the buckets are untouched, which is what makes the
        activation the observable moment of the split.

        PRD: "A new collaboration opens in `DRAFT` with `partner_count` at 0,
        `lead_cost_cents`, `allocated_cost_cents` and `syndication_revenue_cents`
        at 0, `settled_at` null, and `lead_cost_share_bps` seeded from the
        request."

        Design: Difficulty/combinatorial_formula/cf_collaboration_largest_remainder_split_conserves_total_cost
        """
        ctx = _setup_three_way_split_collaboration()

        draft = read_collaboration(ctx["collaboration"]["id"])
        assert draft["status"] == "DRAFT"
        assert draft["lead_cost_cents"] == 0
        assert draft["allocated_cost_cents"] == 0
        assert draft["lead_cost_share_bps"] == 3334
        assert read_partner(ctx["first"]["id"])["cost_owed_cents"] == 0
        assert read_partner(ctx["second"]["id"])["cost_owed_cents"] == 0
