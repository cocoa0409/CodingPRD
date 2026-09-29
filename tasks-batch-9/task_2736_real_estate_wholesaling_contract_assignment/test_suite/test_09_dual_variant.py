"""
Dual-variant computation: one comparable set finalized two ways yields two
different price ceilings, and one lead screened two ways lands on two different
protection tiers.
"""

from decimal import Decimal

from test_helpers import (
    assert_deal_analysis,
    assert_equity_pct_four_places,
    assert_seller_lead,
    build_screened_lead,
    comparable,
    factories,
    make_wholesaler_headers,
    read_lead,
    record_lead,
    register_wholesaler,
    repair_item,
    screen_lead,
    set_clock,
    validate_success,
)

# Five comparables around a 1800 sqft subject; the fifth sits 0.75 miles away
# and so fails the distance filter under both variants.
FIVE_COMPARABLES = [
    comparable(30000000, 0.25, 30, 1850, -500000),
    comparable(31000000, 0.40, 90, 1750, 0),
    comparable(28500000, 0.50, 180, 2100, 250000),
    comparable(32000000, 0.10, 10, 1900, -1000000),
    comparable(40000000, 0.75, 20, 1900, 0),
]

FOUR_REPAIR_ITEMS = [
    repair_item("ROOF", 1200000, 1800000),
    repair_item("HVAC", 600000, 950000),
    repair_item("KITCHEN", 1500000, 2100000),
    repair_item("PLUMBING", 300000, 455000),
]


def _draft_analysis(api, scenario):
    """One DRAFT analysis over the shared comparable set and repair scope."""
    return validate_success(
        api.create_deal_analysis(
            factories.deal_analysis_payload(
                scenario.lead_id,
                scenario.lead["version"],
                subject_gla_sqft=1800,
                comparables=FIVE_COMPARABLES,
                repair_scope_items=FOUR_REPAIR_ITEMS,
            ),
            make_wholesaler_headers(scenario.w_id),
        ),
        201,
    )


class TestValuationVariantsDivergeOnTheCeiling:
    """CONSERVATIVE and AGGRESSIVE disagree on all three outputs."""

    def test_conservative_takes_the_median_and_the_inflated_high_side_repairs(
        self, api
    ):
        """
        "Under `CONSERVATIVE`, the after-repair value is the **median** of the
        qualifying adjusted prices."

        "When the count is even, `arv_cents` is the sum of the two middle
        adjusted prices divided by two, taken to the floor."

        "Under `CONSERVATIVE`, `repair_estimate_cents` is the sum of every line
        item's `high_cents`, multiplied by a contingency factor of 1.10, with
        the sum accumulated first, the multiplication applied once to that sum,
        and the result rounded half up to a whole cent exactly once — the
        contingency is emphatically **not** applied per line item."

        "`max_allowable_offer_cents` is the after-repair value multiplied by
        that variant's multiplier and taken to the floor, then reduced by the
        repair estimate, then reduced by a minimum assignment margin of one
        million cents".

        Design: Difficulty/dual_variant_calc/mao_diverges_between_conservative_and_aggressive_valuation
        """
        scenario = build_screened_lead(api, clock="2026-08-10T00:00:00Z")
        analysis = _draft_analysis(api, scenario)
        assert_deal_analysis(analysis, status="DRAFT", qualifying_comp_count=4)

        finalized = validate_success(
            api.finalize_deal_analysis(
                analysis["id"],
                factories.finalize_payload("CONSERVATIVE"),
                make_wholesaler_headers(scenario.w_id),
            ),
            200,
        )

        # Adjusted prices 28750000, 29500000, 31000000, 31000000; the two middle
        # values average to 30250000. High-side repairs 5305000 x 1.10 rounded
        # once give 5835500, and floor(30250000 * 0.70) == 21175000.
        assert_deal_analysis(
            finalized,
            status="FINALIZED",
            valuation_variant="CONSERVATIVE",
            qualifying_comp_count=4,
            arv_cents=30250000,
            repair_estimate_cents=5835500,
            max_allowable_offer_cents=14339500,
            finalized_at="2026-08-10T00:00:00Z",
        )

    def test_aggressive_weights_by_recency_and_clears_the_conservative_ceiling(
        self, api
    ):
        """
        "Under `AGGRESSIVE`, the after-repair value is a **recency-weighted
        mean** of the qualifying adjusted prices. Each qualifying comparable's
        weight is one hundred and eighty-one minus its `closed_days_ago`, a
        quantity that is always at least 1 because a comparable older than 180
        days cannot qualify. The numerator is the sum over qualifying
        comparables of adjusted price multiplied by weight, the denominator is
        the sum of the weights, both accumulated in full precision; the single
        division is performed once and the quotient rounded half up to a whole
        cent. There is no per-comparable rounding at any point."

        "Under `AGGRESSIVE`, `repair_estimate_cents` is simply the sum of every
        line item's `low_cents`, with no contingency at all."

        "Taken together, `CONSERVATIVE` produces the lower of the two ceilings —
        median value, high-side repairs inflated by contingency, the smaller
        multiplier — and `AGGRESSIVE` the higher."

        Design: Difficulty/dual_variant_calc/mao_diverges_between_conservative_and_aggressive_valuation
        """
        set_clock(api, "2026-08-10T00:00:00Z")
        wholesaler = register_wholesaler(api)
        w_id = wholesaler["id"]
        headers = make_wholesaler_headers(w_id)

        finalized = {}
        for variant, address in (
            ("CONSERVATIVE", factories.LEAD_PROPERTY_ADDRESS),
            ("AGGRESSIVE", factories.SECOND_LEAD_PROPERTY_ADDRESS),
        ):
            lead = record_lead(api, w_id, property_address=address)
            lead = screen_lead(api, lead["id"], w_id, "STATUTORY")
            analysis = validate_success(
                api.create_deal_analysis(
                    factories.deal_analysis_payload(
                        lead["id"],
                        lead["version"],
                        subject_gla_sqft=1800,
                        comparables=FIVE_COMPARABLES,
                        repair_scope_items=FOUR_REPAIR_ITEMS,
                    ),
                    headers,
                ),
                201,
            )
            finalized[variant] = validate_success(
                api.finalize_deal_analysis(
                    analysis["id"], factories.finalize_payload(variant), headers
                ),
                200,
            )

        # 12605250000 / 414 rounded half up once is 30447464, and
        # floor(30447464 * 0.75) == 22835598.
        assert_deal_analysis(
            finalized["AGGRESSIVE"],
            status="FINALIZED",
            valuation_variant="AGGRESSIVE",
            qualifying_comp_count=4,
            arv_cents=30447464,
            repair_estimate_cents=3600000,
            max_allowable_offer_cents=18235598,
        )
        assert_deal_analysis(
            finalized["CONSERVATIVE"],
            arv_cents=30250000,
            repair_estimate_cents=5835500,
            max_allowable_offer_cents=14339500,
        )
        divergence = (
            finalized["AGGRESSIVE"]["max_allowable_offer_cents"]
            - finalized["CONSERVATIVE"]["max_allowable_offer_cents"]
        )
        assert divergence == 3896098, (
            "the identical comparable set must yield two ceilings 3896098 cents "
            f"apart, got {divergence}"
        )


class TestScreeningVariantsDivergeOnTheTier:
    """STATUTORY and EFFECTIVE disagree on what the seller stands to lose."""

    def test_statutory_screen_reads_equity_high_and_lands_on_protected(self, api):
        """
        "Under `STATUTORY`, net equity is the estimated market value less the
        recorded senior lien and nothing else, so equity — and therefore the
        protection tier — reads high."

        "A lead is `PROTECTED` when its equity percentage is at least 0.35
        **and** it carries at least two distress flags."

        Design: Difficulty/dual_variant_calc/protection_tier_diverges_between_statutory_and_effective_screening
        """
        set_clock(api, "2026-08-10T00:00:00Z")
        wholesaler = register_wholesaler(api)
        lead = record_lead(
            api,
            wholesaler["id"],
            owner_name="Priya Nandan",
            property_address="77 Willow Ct, Austin TX",
            estimated_market_value_cents=30000000,
            recorded_senior_lien_cents=18000000,
            junior_lien_cents=1500000,
            delinquent_property_tax_cents=400000,
            distress_flags=["FORECLOSURE_NOTICE", "PROBATE"],
        )

        screened = validate_success(
            api.protection_screen(
                lead["id"],
                factories.protection_screen_payload("STATUTORY"),
                make_wholesaler_headers(wholesaler["id"]),
            ),
            200,
        )

        assert_seller_lead(
            screened,
            status="SCREENED",
            screening_variant="STATUTORY",
            net_equity_cents=12000000,
            protection_tier="PROTECTED",
            screened_at="2026-08-10T00:00:00Z",
            version=2,
        )
        assert_equity_pct_four_places(screened["equity_pct"])
        assert Decimal(str(screened["equity_pct"])) == Decimal("0.4000"), (
            f"12000000 / 30000000 is 0.4000, got {screened['equity_pct']!r}"
        )

    def test_effective_rescreen_deducts_the_rest_and_drops_a_whole_tier(self, api):
        """
        "Under `EFFECTIVE`, net equity is the estimated market value less the
        recorded senior lien, less the junior lien balance, less the delinquent
        property tax, and less a seller closing-cost allowance of eight percent
        of the estimated market value, that allowance being rounded half up to a
        whole cent before it is subtracted. The `EFFECTIVE` variant can
        therefore drop the same lead a whole tier."

        "It is `ELEVATED` in either of two situations: the equity percentage is
        at least 0.35 with exactly one distress flag, or the equity percentage
        is below 0.35 with at least two distress flags."

        Design: Difficulty/dual_variant_calc/protection_tier_diverges_between_statutory_and_effective_screening
        """
        set_clock(api, "2026-08-10T00:00:00Z")
        wholesaler = register_wholesaler(api)
        w_id = wholesaler["id"]
        lead = record_lead(
            api,
            w_id,
            owner_name="Priya Nandan",
            property_address="77 Willow Ct, Austin TX",
            estimated_market_value_cents=30000000,
            recorded_senior_lien_cents=18000000,
            junior_lien_cents=1500000,
            delinquent_property_tax_cents=400000,
            distress_flags=["FORECLOSURE_NOTICE", "PROBATE"],
        )
        statutory = screen_lead(api, lead["id"], w_id, "STATUTORY")

        effective = validate_success(
            api.protection_screen(
                lead["id"],
                factories.protection_screen_payload("EFFECTIVE"),
                make_wholesaler_headers(w_id),
            ),
            200,
        )

        # 30000000 - 18000000 - 1500000 - 400000 - 2400000 == 7700000.
        assert_seller_lead(
            effective,
            status="SCREENED",
            screening_variant="EFFECTIVE",
            net_equity_cents=7700000,
            protection_tier="ELEVATED",
            screened_at="2026-08-10T00:00:00Z",
        )
        assert_equity_pct_four_places(effective["equity_pct"])
        assert Decimal(str(effective["equity_pct"])) == Decimal("0.2567"), (
            "7700000 / 30000000 quantized half up to four places is 0.2567, "
            f"got {effective['equity_pct']!r}"
        )
        assert effective["version"] > statutory["version"], (
            "each screen is a versioned write on the parent lead: "
            f"{statutory['version']} then {effective['version']}"
        )
        assert_seller_lead(
            read_lead(api, lead["id"], w_id),
            protection_tier="ELEVATED",
            net_equity_cents=7700000,
        )
