"""Two-branch pricing and share arithmetic on one and the same ground lease.

The same stream priced perpetually and as a prepaid rent block, the same acquired stream
pledged into a mark-to-model warehouse and a cost-basis warehouse, and the same gross
windfall booked as a colocation, an amendment and a rent increase: in each pair the
branch selector alone moves the money, and these tests pin both sides of every fork.
"""

from test_helpers import (
    ValuationBasis,
    ValuationMethod,
    asset_graph,
    assert_amendment_event,
    assert_borrowing_base,
    assert_fields,
    assert_max_bid_ceiling,
    assert_pledge_eligible_value,
    assert_valuation,
    closed_deal,
    create_facility,
    create_pledge,
    read_facility,
    read_lease_stream,
    record_amendment_event,
    valuation_payload,
    validate_success,
)

# The canonical stream every test below prices: 3,600,000 cents of annual rent, a
# FIXED_PCT escalator of 300 bps, 180 remaining months, and one INVESTMENT_GRADE ANCHOR
# tenancy, which PRD 3.3 scores at 40 points and PRD 3.4 therefore prices at 1000 bps.
EXPECTED_SCORE = 40
EXPECTED_BASE_TIER_BPS = 1000
EXPECTED_GROWTH_BPS = 300

# PRD 3.4 arithmetic on that stream: forty discounted years at 1000 bps with a 2000 bps
# renewal haircut on years 16 through 40 (180 months contracts only 15 years).
LUMP_SUM_VALUE_CENTS = 44_627_011
LUMP_SUM_MAX_BID_CENTS = 46_858_362

# PRD 3.4 arithmetic on the same stream under the prepaid branch: 120 months clipped
# against 180 gives a ten-year horizon, the tier carries a 150 bps term-risk premium,
# no renewal haircut applies, and one 500 bps haircut lands on the finished sum.
PREPAID_DISCOUNT_BPS = 1150
PREPAID_HORIZON_YEARS = 10
PREPAID_VALUE_CENTS = 22_028_616
PREPAID_MAX_BID_CENTS = 23_130_047

# PRD 3.7 on the accepted offer of 36,000,000 cents: a gross at or above 30,000,000 pays
# 150 bps of broker fee, so the commitment the portfolio sets aside is 36,540,000.
CLOSED_DEAL_COMMITMENT_CENTS = 36_540_000

# PRD 3.9 borrowing bases at an advance rate of 6500 bps over an unhaircut PERFORMING
# stream: the model-value pledge and the cost-basis pledge diverge by 5,256,557 cents.
MARK_TO_MODEL_BORROWING_BASE_CENTS = 29_007_557
COST_BASIS_BORROWING_BASE_CENTS = 23_751_000

# PRD 3.8 arithmetic on a gross of 1,000,002 cents at a revenue share of 2500 bps.
AMENDMENT_GROSS_CENTS = 1_000_002
AMENDMENT_CLAIMED_PASS_THROUGH_CENTS = 500_000


# ===========================================================================
# Pricing one stream two ways: perpetual purchase versus prepaid rent block
# ===========================================================================


def test_lump_sum_and_prepaid_valuations_diverge_on_one_stream(api, analyst_headers):
    """Pricing one unchanged stream both ways yields two different values, because the
    method alone changes the horizon, the discount rate and the haircut regime.

    PRD 3.4: "The rounding order in both variants is pinned: each year's present value is rounded before the summation, and the prepaid haircut is applied once to the finished sum."

    Design: Difficulty/dual_variant_calc/valuation_method_variant_divergence_lump_sum_vs_prepaid
    """
    scenario = asset_graph(api)
    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["tenancy_quality_score"] == EXPECTED_SCORE

    lump = validate_success(
        api.create_valuation(
            scenario.lease_stream_id,
            valuation_payload(stream["version"], method=ValuationMethod.LUMP_SUM_PERPETUAL.value),
            headers=analyst_headers,
        ),
        201,
    )

    # Creating a valuation writes nothing back onto the stream, so the second create pins
    # the version the stream currently reports rather than a remembered one.
    stream_again = read_lease_stream(api, scenario.lease_stream_id)
    prepaid = validate_success(
        api.create_valuation(
            scenario.lease_stream_id,
            valuation_payload(
                stream_again["version"],
                method=ValuationMethod.PREPAID_RENT_TERM.value,
                prepaid_term_months=120,
            ),
            headers=analyst_headers,
        ),
        201,
    )

    assert_valuation(lump)
    assert_valuation(prepaid)
    assert_fields(
        lump,
        {
            "method": ValuationMethod.LUMP_SUM_PERPETUAL.value,
            "tenancy_quality_score_snapshot": EXPECTED_SCORE,
            "discount_rate_bps": EXPECTED_BASE_TIER_BPS,
            "growth_rate_bps": EXPECTED_GROWTH_BPS,
            "horizon_years": 40,
            "value_cents": LUMP_SUM_VALUE_CENTS,
        },
        "perpetual valuation",
    )
    assert_fields(
        prepaid,
        {
            "method": ValuationMethod.PREPAID_RENT_TERM.value,
            "tenancy_quality_score_snapshot": EXPECTED_SCORE,
            "discount_rate_bps": PREPAID_DISCOUNT_BPS,
            "growth_rate_bps": EXPECTED_GROWTH_BPS,
            "horizon_years": PREPAID_HORIZON_YEARS,
            "value_cents": PREPAID_VALUE_CENTS,
        },
        "prepaid valuation",
    )
    assert lump["value_cents"] - prepaid["value_cents"] == 22_598_395


def test_perpetual_valuation_prices_forty_years_at_the_bare_tenancy_tier(api, analyst_headers):
    """The perpetual branch discounts a fixed forty-year horizon at the unmodified tier
    rate, haircutting only the years past the contracted term, and its ceiling is 105% of
    that value.

    PRD 3.4: "**Under the `LUMP_SUM_PERPETUAL` method**, `discount_rate_bps` is the base tier unmodified and `horizon_years` is fixed at forty years."

    Design: Difficulty/dual_variant_calc/valuation_method_variant_divergence_lump_sum_vs_prepaid
    """
    scenario = asset_graph(api)
    stream = read_lease_stream(api, scenario.lease_stream_id)

    lump = validate_success(
        api.create_valuation(
            scenario.lease_stream_id,
            valuation_payload(stream["version"], method=ValuationMethod.LUMP_SUM_PERPETUAL.value),
            headers=analyst_headers,
        ),
        201,
    )

    assert_fields(
        lump,
        {
            "status": "DRAFT",
            "discount_rate_bps": EXPECTED_BASE_TIER_BPS,
            "horizon_years": 40,
            "value_cents": LUMP_SUM_VALUE_CENTS,
            "max_bid_cents": LUMP_SUM_MAX_BID_CENTS,
        },
        "perpetual valuation",
    )
    assert_max_bid_ceiling(lump)


def test_prepaid_valuation_clips_its_horizon_and_carries_the_term_risk_premium(api, analyst_headers):
    """The prepaid branch clips its block to the months the lease still has, prices the
    clipped horizon at the tier plus 150 bps, and haircuts the finished sum by 500 bps.

    PRD 3.4: "**Under the `PREPAID_RENT_TERM` method**, the prepaid block is first clipped to what the lease actually still has: the effective month count is the lesser of `prepaid_term_months` and the stream's `remaining_term_months`, and `horizon_years` is that effective month count divided by twelve and truncated toward zero."

    Design: Difficulty/dual_variant_calc/valuation_method_variant_divergence_lump_sum_vs_prepaid
    """
    scenario = asset_graph(api)
    stream = read_lease_stream(api, scenario.lease_stream_id)

    prepaid = validate_success(
        api.create_valuation(
            scenario.lease_stream_id,
            valuation_payload(
                stream["version"],
                method=ValuationMethod.PREPAID_RENT_TERM.value,
                prepaid_term_months=120,
            ),
            headers=analyst_headers,
        ),
        201,
    )

    assert_fields(
        prepaid,
        {
            "status": "DRAFT",
            # 1000 bps base tier plus the 150 bps term-risk premium PRD 3.4 pins.
            "discount_rate_bps": PREPAID_DISCOUNT_BPS,
            # 120 prepaid months clipped against 180 remaining, then divided by twelve.
            "horizon_years": PREPAID_HORIZON_YEARS,
            "value_cents": PREPAID_VALUE_CENTS,
            "max_bid_cents": PREPAID_MAX_BID_CENTS,
        },
        "prepaid valuation",
    )
    assert_max_bid_ceiling(prepaid)


# ===========================================================================
# Pledging one acquired stream into two warehouses on two valuation bases
# ===========================================================================


def _closed_deal_with_two_facilities(api):
    """A closed deal on the canonical stream plus one facility per valuation basis."""
    scenario = closed_deal(api)
    scenario["facility_model"] = create_facility(
        api,
        scenario.portfolio_id,
        facility_name="Warehouse M",
        valuation_basis=ValuationBasis.MARK_TO_MODEL.value,
    )
    scenario["facility_cost"] = create_facility(
        api,
        scenario.portfolio_id,
        facility_name="Warehouse C",
        valuation_basis=ValuationBasis.COST_BASIS.value,
    )
    return scenario


def test_mark_to_model_and_cost_basis_pledges_diverge_on_one_acquired_stream(api):
    """The same acquired stream pledged into two warehouses of equal advance rate produces
    two different borrowing bases, because each facility's basis snapshot reads a
    different number off the same stream.

    PRD 3.9: "`basis_value_cents` follows that snapshot: under `MARK_TO_MODEL` it is the stream's `APPROVED` valuation's `value_cents`; under `COST_BASIS` it is the closed deal's `total_commitment_cents` for that stream."

    Design: Difficulty/dual_variant_calc/facility_valuation_basis_variant_divergence_mark_to_model_vs_cost_basis
    """
    scenario = _closed_deal_with_two_facilities(api)

    model_pledge = create_pledge(
        api,
        scenario["facility_model"]["id"],
        scenario.lease_stream_id,
        pledge_start_date="2026-08-01",
        pledge_end_date="2026-12-31",
    )
    # PRD 2.11 forbids adjacency on closed pledge periods, so the second period starts the
    # day after the first one ends.
    cost_pledge = create_pledge(
        api,
        scenario["facility_cost"]["id"],
        scenario.lease_stream_id,
        pledge_start_date="2027-01-01",
        pledge_end_date="2027-06-30",
    )

    assert_fields(
        model_pledge,
        {
            "valuation_basis_snapshot": ValuationBasis.MARK_TO_MODEL.value,
            "basis_value_cents": LUMP_SUM_VALUE_CENTS,
            "eligible_value_cents": LUMP_SUM_VALUE_CENTS,
        },
        "mark-to-model pledge",
    )
    assert_fields(
        cost_pledge,
        {
            "valuation_basis_snapshot": ValuationBasis.COST_BASIS.value,
            "basis_value_cents": CLOSED_DEAL_COMMITMENT_CENTS,
            "eligible_value_cents": CLOSED_DEAL_COMMITMENT_CENTS,
        },
        "cost-basis pledge",
    )

    model_facility = read_facility(api, scenario["facility_model"]["id"])
    cost_facility = read_facility(api, scenario["facility_cost"]["id"])
    assert model_facility["borrowing_base_cents"] == MARK_TO_MODEL_BORROWING_BASE_CENTS
    assert cost_facility["borrowing_base_cents"] == COST_BASIS_BORROWING_BASE_CENTS
    assert (
        model_facility["borrowing_base_cents"] - cost_facility["borrowing_base_cents"] == 5_256_557
    )


def test_mark_to_model_pledge_values_a_performing_stream_at_the_full_model_value(api):
    """A pledge into a mark-to-model warehouse takes the approved model value as its basis
    and, with the stream performing, carries no haircut at all.

    PRD 3.9: "`haircut_bps` is read from the stream's `servicing_status` — zero basis points while `PERFORMING`, 3000 while on `WATCHLIST`, 5000 while `DELINQUENT`, and the full 10000 while `IMPAIRED`."

    Design: Difficulty/dual_variant_calc/facility_valuation_basis_variant_divergence_mark_to_model_vs_cost_basis
    """
    scenario = closed_deal(api)
    facility = create_facility(
        api,
        scenario.portfolio_id,
        facility_name="Warehouse M",
        valuation_basis=ValuationBasis.MARK_TO_MODEL.value,
    )

    pledge = create_pledge(api, facility["id"], scenario.lease_stream_id)

    assert_fields(
        pledge,
        {
            "status": "PLEDGED",
            "valuation_basis_snapshot": ValuationBasis.MARK_TO_MODEL.value,
            "basis_value_cents": LUMP_SUM_VALUE_CENTS,
            "haircut_bps": 0,
            "eligible_value_cents": LUMP_SUM_VALUE_CENTS,
        },
        "mark-to-model pledge",
    )
    assert_pledge_eligible_value(pledge)

    facility = read_facility(api, facility["id"])
    assert_fields(
        facility,
        {
            "pledged_eligible_total_cents": LUMP_SUM_VALUE_CENTS,
            "concentration_excess_cents": 0,
            "borrowing_base_cents": MARK_TO_MODEL_BORROWING_BASE_CENTS,
            "pledged_stream_count": 1,
            "compliance_state": "COMPLIANT",
        },
        "mark-to-model facility",
    )
    assert_borrowing_base(facility)


def test_cost_basis_pledge_values_the_same_stream_at_the_closed_deal_commitment(api):
    """A pledge into a cost-basis warehouse ignores the model value and takes the closed
    deal's commitment as its basis, so the same collateral supports a smaller base.

    PRD 3.9: "Finally, `borrowing_base_cents` is that concentration-adjusted pool multiplied by `advance_rate_bps`, divided by ten thousand, rounded half up to a whole number of cents."

    Design: Difficulty/dual_variant_calc/facility_valuation_basis_variant_divergence_mark_to_model_vs_cost_basis
    """
    scenario = closed_deal(api)
    facility = create_facility(
        api,
        scenario.portfolio_id,
        facility_name="Warehouse C",
        valuation_basis=ValuationBasis.COST_BASIS.value,
    )

    pledge = create_pledge(api, facility["id"], scenario.lease_stream_id)

    assert_fields(
        pledge,
        {
            "status": "PLEDGED",
            "valuation_basis_snapshot": ValuationBasis.COST_BASIS.value,
            # PRD 3.7: gross 36,000,000 plus a 150 bps broker fee of 540,000.
            "basis_value_cents": CLOSED_DEAL_COMMITMENT_CENTS,
            "haircut_bps": 0,
            "eligible_value_cents": CLOSED_DEAL_COMMITMENT_CENTS,
        },
        "cost-basis pledge",
    )
    assert_pledge_eligible_value(pledge)

    facility = read_facility(api, facility["id"])
    assert_fields(
        facility,
        {
            "pledged_eligible_total_cents": CLOSED_DEAL_COMMITMENT_CENTS,
            "concentration_excess_cents": 0,
            # 36,540,000 at an advance rate of 6500 bps.
            "borrowing_base_cents": COST_BASIS_BORROWING_BASE_CENTS,
            "compliance_state": "COMPLIANT",
        },
        "cost-basis facility",
    )
    assert_borrowing_base(facility)


# ===========================================================================
# Splitting one windfall three ways: colocation, amendment, rent increase
# ===========================================================================


def test_colocation_and_rent_increase_events_split_the_same_gross_differently(api):
    """Booking the identical gross windfall as a colocation and then as a rent increase
    pays the landowner two different amounts, because the rent increase halves the share
    rate the colocation applies in full.

    PRD 3.8: "For a `RENT_INCREASE`, `effective_pass_through_cents` is zero and `share_bps_applied` is the deal's `revenue_share_bps` divided by two and truncated toward zero, on the reasoning that an escalation the acquirer already paid for warrants only half participation."

    Design: Difficulty/dual_variant_calc/amendment_share_variant_divergence_colocation_vs_rent_increase
    """
    scenario = closed_deal(api)
    assert scenario["deal"]["revenue_share_bps"] == 2500

    colocation = record_amendment_event(
        api,
        scenario.lease_stream_id,
        AMENDMENT_GROSS_CENTS,
        event_type="COLOCATION_ADDED",
        effective_date="2026-09-01",
    )
    rent_increase = record_amendment_event(
        api,
        scenario.lease_stream_id,
        AMENDMENT_GROSS_CENTS,
        event_type="RENT_INCREASE",
        effective_date="2026-09-03",
    )

    assert_amendment_event(colocation)
    assert_amendment_event(rent_increase)
    assert_fields(
        colocation,
        {
            "share_bps_applied": 2500,
            "effective_pass_through_cents": 0,
            "net_amount_cents": AMENDMENT_GROSS_CENTS,
            # 1,000,002 at 2500 bps is 250,000.5, which rounds half up to 250,001.
            "landowner_share_cents": 250_001,
            "acquirer_share_cents": 750_001,
        },
        "colocation event",
    )
    assert_fields(
        rent_increase,
        {
            # 2500 bps halved and truncated toward zero.
            "share_bps_applied": 1250,
            "effective_pass_through_cents": 0,
            "net_amount_cents": AMENDMENT_GROSS_CENTS,
            # 1,000,002 at 1250 bps is 125,000.25, which rounds half up to 125,000.
            "landowner_share_cents": 125_000,
            "acquirer_share_cents": 875_002,
        },
        "rent increase event",
    )
    assert colocation["landowner_share_cents"] - rent_increase["landowner_share_cents"] == 125_001


def test_amendment_event_caps_the_claimed_pass_through_before_sharing(api):
    """An amendment recognizes pass-through costs only up to a fifth of gross, so an
    over-claimed cost is trimmed to the cap before the split is taken.

    PRD 3.8: "For an `AMENDMENT`, pass-through costs are recognized but capped: the cap is `gross_amount_cents` multiplied by 2000 basis points divided by ten thousand — twenty percent of gross — rounded half up to a whole number of cents, and `effective_pass_through_cents` is the lesser of the claimed `pass_through_cost_cents` and that cap; `share_bps_applied` is again the deal's `revenue_share_bps` in full."

    Design: Difficulty/dual_variant_calc/amendment_share_variant_divergence_colocation_vs_rent_increase
    """
    scenario = closed_deal(api)

    amendment = record_amendment_event(
        api,
        scenario.lease_stream_id,
        AMENDMENT_GROSS_CENTS,
        event_type="AMENDMENT",
        effective_date="2026-09-02",
        pass_through_cost_cents=AMENDMENT_CLAIMED_PASS_THROUGH_CENTS,
    )

    assert_amendment_event(amendment)
    assert_fields(
        amendment,
        {
            "share_bps_applied": 2500,
            # 1,000,002 at 2000 bps is 200,000.4, rounding half up to 200,000, which is
            # below the 500,000 claimed, so the cap governs.
            "effective_pass_through_cents": 200_000,
            "net_amount_cents": 800_002,
            # 800,002 at 2500 bps is 200,000.5, which rounds half up to 200,001.
            "landowner_share_cents": 200_001,
            "acquirer_share_cents": 600_001,
        },
        "amendment event",
    )


def test_cumulative_revenue_share_accumulates_each_event_split_as_rounded(api):
    """Booking a colocation, an amendment and a rent increase on one acquired stream
    accumulates the three already-rounded splits rather than rounding a summed gross.

    PRD 3.8: "The stream's `cumulative_revenue_share_landowner_cents` and `cumulative_revenue_share_acquirer_cents` then accumulate these **per-event rounded** figures."

    Design: Difficulty/dual_variant_calc/amendment_share_variant_divergence_colocation_vs_rent_increase
    """
    scenario = closed_deal(api)
    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["cumulative_revenue_share_landowner_cents"] == 0
    assert stream["cumulative_revenue_share_acquirer_cents"] == 0

    colocation = record_amendment_event(
        api,
        scenario.lease_stream_id,
        AMENDMENT_GROSS_CENTS,
        event_type="COLOCATION_ADDED",
        effective_date="2026-09-01",
    )
    amendment = record_amendment_event(
        api,
        scenario.lease_stream_id,
        AMENDMENT_GROSS_CENTS,
        event_type="AMENDMENT",
        effective_date="2026-09-02",
        pass_through_cost_cents=AMENDMENT_CLAIMED_PASS_THROUGH_CENTS,
    )
    rent_increase = record_amendment_event(
        api,
        scenario.lease_stream_id,
        AMENDMENT_GROSS_CENTS,
        event_type="RENT_INCREASE",
        effective_date="2026-09-03",
    )

    stream = read_lease_stream(api, scenario.lease_stream_id)
    # 250,001 + 200,001 + 125,000 and 750,001 + 600,001 + 875,002 respectively.
    assert stream["cumulative_revenue_share_landowner_cents"] == 575_002
    assert stream["cumulative_revenue_share_acquirer_cents"] == 2_225_004

    events = (colocation, amendment, rent_increase)
    assert stream["cumulative_revenue_share_landowner_cents"] == sum(
        event["landowner_share_cents"] for event in events
    )
    assert stream["cumulative_revenue_share_acquirer_cents"] == sum(
        event["acquirer_share_cents"] for event in events
    )
    # PRD 3.8's standing invariant: the two cumulative fields exhaust the recorded nets.
    assert stream["cumulative_revenue_share_landowner_cents"] + stream[
        "cumulative_revenue_share_acquirer_cents"
    ] == sum(event["net_amount_cents"] for event in events)
