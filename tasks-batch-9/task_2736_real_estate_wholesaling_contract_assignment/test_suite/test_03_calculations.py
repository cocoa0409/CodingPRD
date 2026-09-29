"""
Derived money and derived percentages: which inputs enter a calculation, the
precision the result is stored at, tier-specific constants, and the
minimum-fee branch of the double-close funding schedule.
"""

from decimal import Decimal

from test_helpers import (
    ApiErrorId,
    assert_assignment_offer,
    assert_deal_analysis,
    assert_equity_pct_four_places,
    assert_nulls,
    assert_purchase_contract,
    assert_seller_lead,
    build_marketed_contract,
    build_screened_lead,
    build_underwritten_lead,
    comparable,
    factories,
    make_wholesaler_headers,
    read_offer,
    register_wholesaler,
    record_lead,
    set_clock,
    validate_error,
    validate_success,
)


class TestValuationInputSet:
    """Which comparables are admitted into the after-repair value."""

    def test_comparable_outside_the_size_band_never_reaches_the_mean(self, api):
        """
        "And its size must sit within twenty percent of the subject's gross
        living area, inclusive — evaluated in exact integer arithmetic so the
        band edge is unambiguous: the absolute difference between the
        comparable's `gla_sqft` and `subject_gla_sqft`, multiplied by one
        hundred, must be at most `subject_gla_sqft` multiplied by twenty."

        "`max_allowable_offer_cents` is the after-repair value multiplied by
        that variant's multiplier and taken to the floor, then reduced by the
        repair estimate, then reduced by a minimum assignment margin of one
        million cents".

        Design: Corner/calculations/comparable_outside_gla_band_is_excluded_from_arv_input_set
        """
        scenario = build_screened_lead(api, clock="2026-08-05T00:00:00Z")
        comparables = list(factories.BASELINE_COMPARABLES) + [
            comparable(40000000, 0.15, 10, 1300, 0)
        ]

        analysis = validate_success(
            api.create_deal_analysis(
                factories.deal_analysis_payload(
                    scenario.lead_id,
                    scenario.lead["version"],
                    comparables=comparables,
                ),
                make_wholesaler_headers(scenario.w_id),
            ),
            201,
        )
        # abs(1300 - 1800) * 100 == 50000 exceeds 1800 * 20 == 36000.
        assert_deal_analysis(analysis, qualifying_comp_count=3)

        finalized = validate_success(
            api.finalize_deal_analysis(
                analysis["id"],
                factories.finalize_payload("AGGRESSIVE"),
                make_wholesaler_headers(scenario.w_id),
            ),
            200,
        )

        assert_deal_analysis(
            finalized,
            status="FINALIZED",
            finalized_at="2026-08-05T00:00:00Z",
            valuation_variant="AGGRESSIVE",
            arv_cents=30000000,
            repair_estimate_cents=1000000,
            max_allowable_offer_cents=20500000,
        )
        assert finalized["arv_cents"] != 32500000, (
            "the excluded 1300 sqft comparable must not raise the after-repair value"
        )
        assert finalized["max_allowable_offer_cents"] != 22375000, (
            "the excluded comparable must not raise the price ceiling"
        )


class TestEquityPercentagePrecision:
    """equity_pct is quantized once, to exactly four decimal places."""

    def test_non_terminating_quotient_is_stored_at_four_places(self, api):
        """
        "From net equity the desk derives `equity_pct` as net equity divided by
        the estimated market value, the division performed once in full
        precision and the result quantized to exactly four decimal places,
        rounded half up; it too may be negative."

        "Under `STATUTORY`, net equity is the estimated market value less the
        recorded senior lien and nothing else, so equity — and therefore the
        protection tier — reads high."

        Design: Corner/calculations/equity_pct_quantised_to_four_decimal_places
        """
        set_clock(api, "2026-08-04T00:00:00Z")
        wholesaler = register_wholesaler(api)
        lead = record_lead(
            api,
            wholesaler["id"],
            estimated_market_value_cents=30000000,
            recorded_senior_lien_cents=10000000,
        )

        response = api.protection_screen(
            lead["id"],
            factories.protection_screen_payload("STATUTORY"),
            make_wholesaler_headers(wholesaler["id"]),
        )
        screened = validate_success(response, 200)

        assert_seller_lead(
            screened,
            status="SCREENED",
            screening_variant="STATUTORY",
            screened_at="2026-08-04T00:00:00Z",
            net_equity_cents=20000000,
            protection_tier="STANDARD",
        )
        assert_equity_pct_four_places(screened["equity_pct"])
        assert Decimal(str(screened["equity_pct"])) == Decimal("0.6667"), (
            "20000000 / 30000000 quantized half up to four places is 0.6667, "
            f"got {screened['equity_pct']!r}"
        )


class TestAssignmentFeeCapConstants:
    """The cap share is selected from the seller's protection tier."""

    def test_elevated_tier_cap_rejects_a_fee_the_standard_cap_would_allow(self, api):
        """
        "The implied assignment fee is the offer's `buyer_price_cents` less the
        contract's `purchase_price_cents`. The cap is a share of the contract
        price that tightens as the seller's protection tier rises: twelve
        percent for a `STANDARD` lead, eight percent for `ELEVATED`, five
        percent for `PROTECTED`. The cap in cents is the contract's
        `purchase_price_cents` multiplied by that share and taken to the floor,
        and the operation is rejected only when the implied fee is **strictly
        greater** than the cap — a fee landing exactly on the cap is permitted."

        "It is `ELEVATED` in either of two situations: the equity percentage is
        at least 0.35 with exactly one distress flag, or the equity percentage
        is below 0.35 with at least two distress flags."

        Design: Corner/calculations/assignment_fee_cap_uses_elevated_rate_for_single_flag_lead
        """
        scenario = build_marketed_contract(
            api,
            clock="2026-08-06T00:00:00Z",
            buyer_price_cents=19656001,
            structure_election="ASSIGNMENT_ELECTED",
            lead_kwargs={
                "estimated_market_value_cents": 30000000,
                "recorded_senior_lien_cents": 500000,
                "distress_flags": ["FORECLOSURE_NOTICE"],
            },
            contract_kwargs={
                "purchase_price_cents": 18200000,
                "earnest_money_cents": 500000,
            },
        )
        assert_seller_lead(scenario.lead, protection_tier="ELEVATED")

        response = api.accept_assignment_offer(scenario.offer_id, scenario.w_headers)
        validate_error(response, ApiErrorId.ASSIGNMENT_FEE_CAP_EXCEEDED, 422)

        # The implied fee 19656001 - 18200000 == 1456001 clears the ELEVATED cap
        # floor(18200000 * 0.08) == 1456000 by one cent, and would have sat well
        # inside the STANDARD cap floor(18200000 * 0.12) == 2184000.
        after = read_offer(api, scenario.offer_id, scenario.w_id)
        assert_assignment_offer(after, status="SUBMITTED")
        assert_nulls(
            after, "accepted_at", "assignment_fee_cents", label="assignment_offer"
        )


class TestDoubleCloseFundingSchedule:
    """The tier minimum fee floors the percentage product."""

    def test_tier_one_minimum_fee_floors_a_small_percentage_product(self, api):
        """
        "Step one grosses up the purchase price with closing and recording
        costs: `funding_base_cents` is `purchase_price_cents` plus two point one
        percent of `purchase_price_cents`, that percentage product rounded half
        up to a whole cent before it is added."

        "A base below fifteen million cents (one hundred and fifty thousand
        dollars) sits in the first tier, at a rate of three percent with a
        minimum fee of twenty-five thousand cents."

        "Step three applies the tier: `transactional_lender_fee_cents` is the
        greater of that tier's minimum fee and the base multiplied by the tier
        rate, the product rounded half up to a whole cent **before** the
        minimum-fee floor is applied. Step four totals:
        `total_funding_required_cents` is `funding_base_cents` plus
        `transactional_lender_fee_cents`."

        Design: Corner/calculations/double_close_funding_fee_uses_tier_minimum_floor
        """
        scenario = build_underwritten_lead(api, clock="2026-08-07T00:00:00Z")
        contract = validate_success(
            api.create_purchase_contract(
                factories.purchase_contract_payload(
                    scenario.lead_id,
                    scenario.analysis_id,
                    purchase_price_cents=700000,
                    earnest_money_cents=50000,
                    option_start_at="2026-08-07T00:00:00Z",
                ),
                make_wholesaler_headers(scenario.w_id),
            ),
            201,
        )

        response = api.elect_structure(
            contract["id"],
            factories.elect_structure_payload("DOUBLE_CLOSE_ELECTED"),
            make_wholesaler_headers(scenario.w_id),
        )
        elected = validate_success(response, 200)

        assert_purchase_contract(
            elected,
            structure_election="DOUBLE_CLOSE_ELECTED",
            contract_status="DRAFT",
            funding_base_cents=714700,
            transactional_lender_fee_cents=25000,
            total_funding_required_cents=739700,
        )
        assert_nulls(elected, "double_close_spread_cents", label="purchase_contract")
