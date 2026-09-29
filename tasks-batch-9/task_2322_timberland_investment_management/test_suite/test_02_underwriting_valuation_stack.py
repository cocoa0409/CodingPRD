"""The underwriting valuation stack: growth variants, non-timber components and the fee tier."""

from test_helpers import assert_money, assert_tons
from test_helpers.fixtures import create_case, cruised_stand

BIG_THICKET_PROPERTY = {
    "name": "Big Thicket Tract",
    "total_acres": 2000.00,
    "haul_distance_miles": 62,
    "hbu_acres": 40.00,
    "hbu_price_per_acre_usd": 3000.00,
    "annual_rec_income_usd": 18000.00,
    "certification_scheme": "SFI",
}
BIG_THICKET_STAND = {"stand_code": "BT-01", "acres": 1860.00}


def _big_thicket(api):
    """A 2000.00-acre tract carrying one 1860.00-acre stand cruised to 72030.36 tons."""
    return cruised_stand(
        api,
        property_overrides=BIG_THICKET_PROPERTY,
        stand_overrides=BIG_THICKET_STAND,
    )


class TestGrowthVariantDivergence:
    """The geometric and arithmetic growth curves priced off one identical inventory."""

    def test_the_yield_table_variant_compounds_off_the_standing_volume(self, api):
        """A YIELD_TABLE case raises the growth factor to the power of the years projected.

        PRD: "Under `YIELD_TABLE`, the projected volume is the base tonnage multiplied by the factor one plus the species' periodic growth percentage divided by one hundred, that factor raised to the power of the whole number of years being projected, and the single result rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/underwriting_growth_variant_yield_table_vs_mai_linear_diverges
        """
        ctx = _big_thicket(api)
        assert_tons(ctx.stand["net_merch_tons"], 72030.36, "net_merch_tons")

        case = create_case(api, ctx.property_id, growth_variant="YIELD_TABLE")

        assert_money(case["timber_pv_usd"], 3020794.10, "timber_pv_usd")
        assert_money(case["pre_fee_value_usd"], 3257794.10, "pre_fee_value_usd")
        assert_money(case["underwritten_value_usd"], 3233360.64, "underwritten_value_usd")

    def test_the_mai_linear_variant_adds_a_fixed_increment_per_acre_per_year(self, api):
        """A MAI_LINEAR case adds the species increment across the stand acreage instead of compounding.

        PRD: "Under `MAI_LINEAR`, the projected volume is the base tonnage plus the species' mean annual increment per acre per year multiplied by the stand acreage and by the whole number of years, again rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/underwriting_growth_variant_yield_table_vs_mai_linear_diverges
        """
        ctx = _big_thicket(api)

        case = create_case(api, ctx.property_id, growth_variant="MAI_LINEAR")

        assert_money(case["timber_pv_usd"], 3080948.07, "timber_pv_usd")
        assert_money(case["pre_fee_value_usd"], 3317948.07, "pre_fee_value_usd")
        assert_money(case["underwritten_value_usd"], 3293063.46, "underwritten_value_usd")

    def test_the_two_variants_diverge_only_on_the_timber_leg(self, api):
        """On one tract the variants share their non-timber components and differ by 59702.82.

        PRD: "so the same inputs under different variants must be expected to produce different values"

        Design: Difficulty/dual_variant_calc/underwriting_growth_variant_yield_table_vs_mai_linear_diverges
        """
        ctx = _big_thicket(api)

        yield_table = create_case(api, ctx.property_id, growth_variant="YIELD_TABLE")
        mai_linear = create_case(api, ctx.property_id, growth_variant="MAI_LINEAR")

        assert_money(yield_table["hbu_premium_usd"], 120000.00, "YIELD_TABLE hbu_premium_usd")
        assert_money(mai_linear["hbu_premium_usd"], 120000.00, "MAI_LINEAR hbu_premium_usd")
        assert_money(
            yield_table["rec_income_pv_usd"], 117000.00, "YIELD_TABLE rec_income_pv_usd"
        )
        assert_money(
            mai_linear["rec_income_pv_usd"], 117000.00, "MAI_LINEAR rec_income_pv_usd"
        )

        delta = float(mai_linear["underwritten_value_usd"]) - float(
            yield_table["underwritten_value_usd"]
        )
        assert_money(delta, 59702.82, "underwritten value delta")

    def test_the_non_timber_components_are_multiples_of_the_tract_assumptions(self, api):
        """The HBU premium and the recreational income present value come straight off the tract.

        PRD: "`rec_income_pv_usd` is the property's `annual_rec_income_usd` multiplied by six and one half, rounded half-up to two decimals"

        Design: Difficulty/dual_variant_calc/underwriting_growth_variant_yield_table_vs_mai_linear_diverges
        """
        ctx = _big_thicket(api)

        case = create_case(api, ctx.property_id, growth_variant="YIELD_TABLE")

        assert_money(case["hbu_premium_usd"], 120000.00, "hbu_premium_usd")
        assert_money(case["rec_income_pv_usd"], 117000.00, "rec_income_pv_usd")


class TestAcquisitionFeeTierKeying:
    """The fee tier is chosen from the pre-fee figure, which the post-fee figure can fall below."""

    def test_the_tier_is_selected_from_the_pre_fee_value(self, api):
        """A pre-fee value at or above the second breakpoint earns the 0.75 percent tier.

        PRD: "The acquisition fee is tiered, and the tier is keyed on `pre_fee_value_usd` — never on the post-fee figure."

        Design: Difficulty/combinatorial_formula/acquisition_fee_tier_keyed_on_pre_fee_value_not_post_fee
        """
        ctx = _big_thicket(api)

        case = create_case(api, ctx.property_id, growth_variant="YIELD_TABLE")

        assert_money(case["timber_pv_usd"], 3020794.10, "timber_pv_usd")
        assert_money(case["pre_fee_value_usd"], 3257794.10, "pre_fee_value_usd")
        assert float(case["acquisition_fee_pct"]) == 0.75
        assert_money(case["acquisition_fee_usd"], 24433.46, "acquisition_fee_usd")
        assert case["status"] == "DRAFT"

    def test_the_post_fee_value_falls_back_below_the_breakpoint_it_cleared(self, api):
        """Subtracting the fee drops the value under 3250000.00, which must not change the tier.

        PRD: "Selecting the tier from `underwritten_value_usd` is the natural mistake and is wrong: subtracting the fee can drop the value back below a breakpoint that the pre-fee figure cleared."

        Design: Difficulty/combinatorial_formula/acquisition_fee_tier_keyed_on_pre_fee_value_not_post_fee
        """
        ctx = _big_thicket(api)

        case = create_case(api, ctx.property_id, growth_variant="YIELD_TABLE")

        assert_money(case["underwritten_value_usd"], 3233360.64, "underwritten_value_usd")
        assert float(case["underwritten_value_usd"]) < 3250000.00
        assert abs(float(case["acquisition_fee_usd"]) - 32577.94) > 0.01, (
            "the fee must not have been struck at the 1.00 percent tier"
        )
        assert abs(float(case["underwritten_value_usd"]) - 3225216.16) > 0.01, (
            "the underwritten value must not reflect a post-fee tier selection"
        )
