"""Tiered stormwater utility fee: per-tier rounding and the ERU half-up boundary."""

import pytest

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_fee_chain, assert_two_dp


@pytest.fixture
def billing_term():
    """An ACTIVE term whose ERU denominator is 3000 square feet."""
    return fx.setup_active_program(eru_sqft=3000, funding_target_cents=25000)


class TestTierComponentRounding:
    """Each tier component is rounded on its own before the three are added."""

    def test_01_commercial_parcel_straddling_two_tiers_bills_each_component_rounded(
        self, billing_term
    ):
        """A 9020 sqft COMMERCIAL parcel bills 29264, not the round-once 29265.

        PRD: "Each tier's component is computed and **rounded to whole cents on
        its own**, and only then are the three components added together to give
        `gross_fee_cents`; summing the three unrounded components and rounding
        once at the end is wrong and diverges by a cent on parcels straddling a
        tier boundary."

        Design: Difficulty/combinatorial_formula/utility_fee_rounds_each_tier_component_before_summing
        """
        account = fx.create_account(
            billing_term["term_id"],
            parcel_id="P-9020",
            parcel_class="COMMERCIAL",
            impervious_area_sqft=9020,
            owner_name="Harborline Retail LLC",
        )

        assert_fee_chain(
            account,
            eru_units=3.01,
            gross_fee_cents=26129,
            class_surcharge_cents=3135,
            gross_billable_cents=29264,
        )
        assert account["gross_billable_cents"] != 29265, (
            "29265 is the result of summing the unrounded tier components and "
            "rounding once at the end"
        )

    def test_02_institutional_parcel_reaching_the_third_tier_bills_all_three_components(
        self, billing_term
    ):
        """A 15400 sqft INSTITUTIONAL parcel bills 9633 + 24621 + 7391 plus 8 percent.

        PRD: "The first tier bills 9633 cents per unit, the second 8207 cents
        per unit and the third 6541 cents per unit."

        Design: Difficulty/combinatorial_formula/utility_fee_rounds_each_tier_component_before_summing
        """
        account = fx.create_account(
            billing_term["term_id"],
            parcel_id="P-15400",
            parcel_class="INSTITUTIONAL",
            impervious_area_sqft=15400,
            owner_name="Ridge Academy",
        )

        assert_fee_chain(
            account,
            eru_units=5.13,
            gross_fee_cents=41645,
            class_surcharge_cents=3332,
            gross_billable_cents=44977,
        )

    def test_03_term_revenue_projection_sums_the_billed_parcels(self, billing_term):
        """Opening two accounts projects 74241 cents of annual revenue.

        PRD: "It also raises the term's `projected_annual_revenue_cents` and
        refreshes `funding_adequacy_status`."

        Design: Difficulty/combinatorial_formula/utility_fee_rounds_each_tier_component_before_summing
        """
        fx.create_account(
            billing_term["term_id"],
            parcel_id="P-9020",
            parcel_class="COMMERCIAL",
            impervious_area_sqft=9020,
        )
        fx.create_account(
            billing_term["term_id"],
            parcel_id="P-15400",
            parcel_class="INSTITUTIONAL",
            impervious_area_sqft=15400,
        )

        term = fx.read_term(billing_term["term_id"])
        assert_cents(
            term["projected_annual_revenue_cents"], 74241, "projected_annual_revenue_cents"
        )
        assert term["funding_adequacy_status"] == "ADEQUATE", (
            "revenue of 74241 cents meets the 25000-cent target, so the programme "
            "is adequately funded"
        )


class TestEruHalfUpBoundary:
    """One hundredth of an ERU moves the whole cent ladder."""

    @pytest.mark.parametrize(
        "parcel_id,impervious,eru_units,gross,surcharge,billable",
        [
            ("P-12000", 12000, 4.00, 34254, 1713, 35967),
            ("P-12044", 12044, 4.01, 34319, 1716, 36035),
            ("P-12045", 12045, 4.02, 34385, 1719, 36104),
        ],
    )
    def test_04_eru_units_round_half_up_and_shift_the_third_tier_component(
        self, billing_term, parcel_id, impervious, eru_units, gross, surcharge, billable
    ):
        """12045 sqft is exactly 4.015 ERU and rounds up to 4.02.

        PRD: "`eru_units` is `impervious_area_sqft` divided by the term's
        `eru_sqft`, rounded to 2 decimal places."

        Design: Difficulty/boundary_precision_check/eru_half_up_at_exact_half_shifts_the_whole_cent_ladder
        """
        account = fx.create_account(
            billing_term["term_id"],
            parcel_id=parcel_id,
            parcel_class="RESIDENTIAL_MULTI",
            impervious_area_sqft=impervious,
        )

        assert_two_dp(account["eru_units"], eru_units, "eru_units")
        assert_fee_chain(
            account,
            eru_units=eru_units,
            gross_fee_cents=gross,
            class_surcharge_cents=surcharge,
            gross_billable_cents=billable,
        )

    def test_05_every_money_field_is_a_whole_number_of_cents(self, billing_term):
        """No account response carries a fractional cent.

        PRD: "Money is always an integer number of cents."

        Design: Difficulty/boundary_precision_check/eru_half_up_at_exact_half_shifts_the_whole_cent_ladder
        """
        account = fx.create_account(
            billing_term["term_id"],
            parcel_id="P-12045",
            parcel_class="RESIDENTIAL_MULTI",
            impervious_area_sqft=12045,
        )

        for field in (
            "gross_fee_cents",
            "class_surcharge_cents",
            "gross_billable_cents",
            "current_net_fee_cents",
        ):
            assert isinstance(account[field], int), (
                f"{field} must be an integer number of cents, got {account[field]!r}"
            )

    def test_06_term_revenue_accumulates_the_three_boundary_parcels(self, billing_term):
        """The three parcels straddling the 4.00 ERU break project 108106 cents.

        PRD: "`gross_billable_cents` is `gross_fee_cents` plus
        `class_surcharge_cents`."

        Design: Difficulty/boundary_precision_check/eru_half_up_at_exact_half_shifts_the_whole_cent_ladder
        """
        for parcel_id, impervious in (
            ("P-12000", 12000),
            ("P-12044", 12044),
            ("P-12045", 12045),
        ):
            fx.create_account(
                billing_term["term_id"],
                parcel_id=parcel_id,
                parcel_class="RESIDENTIAL_MULTI",
                impervious_area_sqft=impervious,
            )

        term = fx.read_term(billing_term["term_id"])
        assert_cents(
            term["projected_annual_revenue_cents"], 108106, "projected_annual_revenue_cents"
        )
