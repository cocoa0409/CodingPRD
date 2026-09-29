"""Composed money formulas across the buyout pipeline.

These tests exercise the three places where the API multiplies several independent inputs
together in one pinned order: the forty-year lump-sum present value that composes escalator
growth, the score-derived discount rate and the renewal-risk haircut; the settlement
statement whose broker tier is picked on gross before any dispute holdback is subtracted;
and the warehouse borrowing base that deducts per-anchor-carrier concentration excess before
applying the advance rate.
"""

from test_helpers import (
    CarrierCreditTier,
    DisputeType,
    Scenario,
    TenancyType,
    ValuationMethod,
    add_tenancy,
    assert_borrowing_base,
    assert_pledge_eligible_value,
    assert_portfolio_ledger_balances,
    assert_settlement_arithmetic,
    assert_utilization_and_posture,
    closed_deal,
    create_facility,
    create_landowner,
    create_lease_stream,
    create_pledge,
    create_portfolio,
    create_tower_company,
    create_tower_site,
    create_valuation,
    deal_in_negotiation,
    make_acquisition_analyst_headers,
    make_platform_admin_headers,
    make_treasury_officer_headers,
    open_dispute,
    read_facility,
    read_lease_stream,
    validate_success,
)

# The canonical stream the PRD's own arithmetic is worked against: 3,600,000 cents of
# annual ground rent with 180 months left to run, so fifteen years are contracted and
# years sixteen through forty carry the renewal-risk haircut.
ANNUAL_RENT_CENTS = 3_600_000
REMAINING_TERM_MONTHS = 180

# Model values produced by the PRD's per-year walk on that stream at a 1000 bps discount.
VALUE_AT_FIXED_300_BPS = 44_627_011
VALUE_AT_FIXED_400_BPS = 49_734_665
VALUE_AT_CPI_CAPPED_400_BPS = 42_393_442
MAX_BID_AT_FIXED_300_BPS = 46_858_362


def _lump_sum_valuation(
    api,
    tower_company_id,
    *,
    site_code,
    owner_slug,
    escalator_type,
    escalator_pct_bps,
):
    """Register one site, owner and stream, give it a single investment-grade anchor, price it."""
    site = create_tower_site(api, tower_company_id, site_code=site_code)
    owner = create_landowner(
        api, legal_name=f"Owner {owner_slug} LLC", contact_email=f"owner_{owner_slug}@x.example"
    )
    stream = create_lease_stream(
        api,
        site["id"],
        owner["id"],
        current_annual_rent_cents=ANNUAL_RENT_CENTS,
        escalator_type=escalator_type,
        escalator_pct_bps=escalator_pct_bps,
        remaining_term_months=REMAINING_TERM_MONTHS,
    )
    add_tenancy(
        api,
        stream["id"],
        carrier_credit_tier=CarrierCreditTier.INVESTMENT_GRADE.value,
        tenancy_type=TenancyType.ANCHOR.value,
    )
    return create_valuation(api, stream["id"], method=ValuationMethod.LUMP_SUM_PERPETUAL.value)


def _two_acquired_streams_under_distinct_anchor_carriers(api):
    """One capital pool funding two closed deals whose streams name different anchors."""
    portfolio = create_portfolio(api, total_capital_cents=120_000_000)
    legs = []
    for site_code, carrier, slug, recording_ref in (
        ("NE-3001", "Vantage Wireless", "v", "BK1500-PG100"),
        ("NE-3002", "Crestline Mobility", "c", "BK1500-PG200"),
    ):
        legs.append(
            closed_deal(
                api,
                existing=Scenario(portfolio=portfolio),
                tower_site={"site_code": site_code},
                landowner={
                    "legal_name": f"Owner {slug} LLC",
                    "contact_email": f"owner_{slug}@x.example",
                },
                tenancies=({"carrier_name": carrier},),
                recording_ref=recording_ref,
            )
        )
    return portfolio, legs[0], legs[1]


# ===========================================================================
# The forty-year lump-sum present value
# ===========================================================================


def test_lump_sum_valuation_composes_fixed_growth_discounting_and_the_renewal_haircut(api):
    """Pricing a stream that escalates 300 bps a year with fifteen contracted years left
    produces the forty-year present value the PRD's per-year walk defines.

    PRD 3.4: "For a year *y*, the modelled rent is `current_annual_rent_cents` multiplied by the quantity one plus `growth_rate_bps` divided by ten thousand, raised to the power of *y* minus one."
    PRD 3.4: "If *y* is strictly greater than the contracted-years count, the year lies beyond the signed term and its present value is reduced by a renewal-risk haircut of 2000 basis points — that is, multiplied by the quantity one less two thousand divided by ten thousand."
    PRD 3.4: "`value_cents` is the sum of those rounded per-year figures."

    Design: Difficulty/combinatorial_formula/valuation_npv_composes_growth_compounding_discounting_and_renewal_haircut
    """
    company = create_tower_company(api)
    valuation = _lump_sum_valuation(
        api,
        company["id"],
        site_code="NE-2001",
        owner_slug="f3",
        escalator_type="FIXED_PCT",
        escalator_pct_bps=300,
    )

    assert valuation["tenancy_quality_score_snapshot"] == 40, (
        "one ACTIVE INVESTMENT_GRADE ANCHOR tenancy scores forty points"
    )
    assert valuation["discount_rate_bps"] == 1000, (
        "a snapshot score of 40 lands on the 1000 bps rung of the discount ladder"
    )
    assert valuation["growth_rate_bps"] == 300, "FIXED_PCT carries escalator_pct_bps verbatim"
    assert valuation["horizon_years"] == 40, "the perpetual method fixes the horizon at forty years"
    assert valuation["value_cents"] == VALUE_AT_FIXED_300_BPS, (
        f"value_cents is {valuation['value_cents']}, expected {VALUE_AT_FIXED_300_BPS} from the "
        "forty-year walk with years sixteen through forty haircut 2000 bps"
    )
    assert valuation["max_bid_cents"] == MAX_BID_AT_FIXED_300_BPS
    assert valuation["status"] == "DRAFT"


def test_a_higher_fixed_escalator_lifts_the_modelled_stream_value(api):
    """Two otherwise identical streams priced side by side differ only in their fixed
    escalator, and the escalator moves the present value on its own.

    PRD 3.4: "`FIXED_PCT` gives the stream's `escalator_pct_bps` verbatim."
    PRD 3.4: "The discount factor for that year is one divided by the quantity one plus `discount_rate_bps` divided by ten thousand, raised to the power of *y*."

    Design: Difficulty/combinatorial_formula/valuation_npv_composes_growth_compounding_discounting_and_renewal_haircut
    """
    company = create_tower_company(api)
    slower = _lump_sum_valuation(
        api,
        company["id"],
        site_code="NE-2001",
        owner_slug="f3",
        escalator_type="FIXED_PCT",
        escalator_pct_bps=300,
    )
    faster = _lump_sum_valuation(
        api,
        company["id"],
        site_code="NE-2002",
        owner_slug="f4",
        escalator_type="FIXED_PCT",
        escalator_pct_bps=400,
    )

    assert slower["growth_rate_bps"] == 300
    assert faster["growth_rate_bps"] == 400
    assert slower["discount_rate_bps"] == faster["discount_rate_bps"] == 1000, (
        "both streams score 40, so the discount rung is identical and only growth differs"
    )
    assert slower["value_cents"] == VALUE_AT_FIXED_300_BPS
    assert faster["value_cents"] == VALUE_AT_FIXED_400_BPS
    assert faster["value_cents"] - slower["value_cents"] == 5_107_654, (
        "the hundred-basis-point escalator step compounds into a fixed value difference"
    )


def test_cpi_capped_escalator_is_modelled_at_the_inflation_ceiling(api):
    """A stream whose CPI-linked escalator is stated at 400 bps is modelled at 250 bps, so
    it prices below an otherwise identical stream with a flat 400 bps escalator.

    PRD 3.4: "`CPI_CAPPED` gives the lesser of `escalator_pct_bps` and an assumed inflation rate of 250 basis points, so a stream with a 400-basis-point CPI-linked escalator is modelled at 250."

    Design: Difficulty/combinatorial_formula/valuation_npv_composes_growth_compounding_discounting_and_renewal_haircut
    """
    company = create_tower_company(api)
    capped = _lump_sum_valuation(
        api,
        company["id"],
        site_code="NE-2003",
        owner_slug="c4",
        escalator_type="CPI_CAPPED",
        escalator_pct_bps=400,
    )
    uncapped = _lump_sum_valuation(
        api,
        company["id"],
        site_code="NE-2002",
        owner_slug="f4",
        escalator_type="FIXED_PCT",
        escalator_pct_bps=400,
    )

    assert capped["growth_rate_bps"] == 250, "the 250 bps inflation ceiling overrides the stated 400"
    assert uncapped["growth_rate_bps"] == 400
    assert capped["value_cents"] == VALUE_AT_CPI_CAPPED_400_BPS, (
        f"value_cents is {capped['value_cents']}, expected {VALUE_AT_CPI_CAPPED_400_BPS} once growth "
        "is clipped to 250 bps"
    )
    assert uncapped["value_cents"] == VALUE_AT_FIXED_400_BPS
    assert capped["value_cents"] < uncapped["value_cents"]


# ===========================================================================
# The settlement statement: tier on gross, then fee, then holdback, then net
# ===========================================================================


def test_broker_fee_is_keyed_on_gross_consideration_not_the_post_holdback_net(api):
    """Accepting a 36,000,000 cent offer while one dispute is unresolved computes the broker
    fee on the gross figure, not on the smaller net that the holdback leaves behind.

    PRD 3.7: "The order of that computation is pinned: the broker tier is selected on gross, then the fee is computed, then the holdback, then the net."
    PRD 3.7: "`broker_fee_cents` is gross multiplied by `broker_fee_bps`, divided by ten thousand, rounded half up to a whole number of cents."

    Design: Difficulty/combinatorial_formula/settlement_broker_tier_keyed_on_gross_before_dispute_holdback
    """
    scenario = deal_in_negotiation(api)
    open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.ACCESS.value,
        description="Gate lock changed without notice",
    )

    accepted = validate_success(
        api.transition_offer(scenario.offer_id, {"action": "ACCEPT"}, headers=scenario.landowner_headers)
    )
    assert accepted["status"] == "ACCEPTED"

    settlement = validate_success(
        api.get_settlement(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert settlement["agreed_consideration_cents"] == 36_000_000
    assert settlement["broker_fee_bps"] == 150, "a gross at or above 30,000,000 cents sets the tier to 150 bps"
    assert settlement["broker_fee_cents"] == 540_000, (
        f"broker_fee_cents is {settlement['broker_fee_cents']}, expected 540000 from 150 bps of gross"
    )
    assert settlement["broker_fee_cents"] != 526_500, (
        "526500 is 150 bps of the post-holdback net, which is the wrong base for the fee"
    )
    assert settlement["holdback_cents"] == 900_000, "one unresolved dispute holds back 250 bps of gross"
    assert settlement["net_landowner_proceeds_cents"] == 35_100_000
    assert settlement["total_commitment_cents"] == 36_540_000
    assert_settlement_arithmetic(settlement, expected_open_dispute_count=1)


def test_two_unresolved_disputes_double_the_holdback_without_moving_the_broker_fee(api):
    """A second unresolved dispute of a different type raises the holdback to 500 bps of
    gross while the broker fee, keyed on gross alone, does not move.

    PRD 3.7: "The holdback rate is that count multiplied by 250 basis points, capped at 1000 basis points — so from four unresolved disputes onward the holdback stops growing at ten percent of gross."
    PRD 3.7: "`net_landowner_proceeds_cents` is gross less `holdback_cents`, and `total_commitment_cents` — the figure the portfolio actually has to set aside — is gross plus `broker_fee_cents`."

    Design: Difficulty/combinatorial_formula/settlement_broker_tier_keyed_on_gross_before_dispute_holdback
    """
    scenario = deal_in_negotiation(api)
    open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.ACCESS.value,
        description="Gate lock changed without notice",
    )
    open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.INTERFERENCE.value,
        description="Generator noise across the boundary",
    )

    validate_success(
        api.transition_offer(scenario.offer_id, {"action": "ACCEPT"}, headers=scenario.landowner_headers)
    )

    settlement = validate_success(
        api.get_settlement(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert settlement["agreed_consideration_cents"] == 36_000_000
    assert settlement["broker_fee_bps"] == 150
    assert settlement["broker_fee_cents"] == 540_000, "the fee stays on gross however large the holdback grows"
    assert settlement["holdback_cents"] == 1_800_000, "two unresolved disputes hold back 500 bps of gross"
    assert settlement["net_landowner_proceeds_cents"] == 34_200_000
    assert settlement["total_commitment_cents"] == 36_540_000, (
        "the commitment is gross plus the broker fee and is untouched by the holdback"
    )
    assert_settlement_arithmetic(settlement, expected_open_dispute_count=2)


def test_acceptance_reserves_gross_plus_broker_fee_against_the_capital_pool(api):
    """The commitment the pool sets aside on acceptance is gross plus the broker fee, and the
    portfolio's utilization is recomputed from that figure.

    PRD 3.1: "`committed_capital_cents` is the sum of `total_commitment_cents` across deals whose `capital_state` is `RESERVED` or `ESCROWED`."
    PRD 3.1: "Utilization is measured against the whole pool: let *used* be the sum of `committed_capital_cents` and `deployed_capital_cents`; then `utilization_bps` is zero when `total_capital_cents` is zero, and otherwise is *used* multiplied by ten thousand, divided by `total_capital_cents`, and rounded half up to a whole number of basis points."

    Design: Difficulty/combinatorial_formula/settlement_broker_tier_keyed_on_gross_before_dispute_holdback
    """
    scenario = deal_in_negotiation(api)
    open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.ACCESS.value,
        description="Gate lock changed without notice",
    )

    validate_success(
        api.transition_offer(scenario.offer_id, {"action": "ACCEPT"}, headers=scenario.landowner_headers)
    )

    deal = validate_success(api.get_deal(scenario.deal_id, headers=make_acquisition_analyst_headers()))
    assert deal["capital_state"] == "RESERVED"
    assert deal["stage"] == "DILIGENCE"

    portfolio = validate_success(
        api.get_portfolio(scenario.portfolio_id, headers=make_platform_admin_headers())
    )
    assert portfolio["committed_capital_cents"] == 36_540_000, (
        "the reservation is the gross consideration plus the 540000 cent broker fee"
    )
    assert portfolio["deployed_capital_cents"] == 0
    assert portfolio["available_capital_cents"] == 13_460_000
    assert portfolio["utilization_bps"] == 7308, (
        f"utilization_bps is {portfolio['utilization_bps']}, expected 7308 from 36540000 of 50000000"
    )
    assert portfolio["capital_posture"] == "OPEN"
    assert_portfolio_ledger_balances(portfolio)
    assert_utilization_and_posture(portfolio)


# ===========================================================================
# The warehouse borrowing base: concentration deduction, then advance rate
# ===========================================================================


def test_two_anchor_carriers_exactly_at_the_concentration_ceiling_leave_the_base_undeducted(api):
    """Two equal pledges under different anchor carriers each sit exactly at a 5000 bps
    per-carrier ceiling, so no concentration excess is deducted before the advance rate.

    PRD 3.9: "Second comes the carrier concentration test, keyed on each pledged stream's `anchor_carrier_name`: the per-carrier ceiling is the gross eligible pool multiplied by `carrier_concentration_limit_bps`, divided by ten thousand, rounded half up to a whole number of cents; each anchor carrier's total is the sum of `eligible_value_cents` across the pledges whose streams name that carrier as anchor; and `concentration_excess_cents` is the sum, across carriers, of the amount by which a carrier's total exceeds the ceiling, counting zero for any carrier at or below the ceiling."
    PRD 3.9: "Finally, `borrowing_base_cents` is that concentration-adjusted pool multiplied by `advance_rate_bps`, divided by ten thousand, rounded half up to a whole number of cents."

    Design: Difficulty/combinatorial_formula/facility_borrowing_base_composes_concentration_cap_then_advance_rate
    """
    portfolio, leg_v, leg_c = _two_acquired_streams_under_distinct_anchor_carriers(api)

    stream_v = read_lease_stream(api, leg_v.lease_stream_id)
    stream_c = read_lease_stream(api, leg_c.lease_stream_id)
    assert stream_v["anchor_carrier_name"] == "Vantage Wireless"
    assert stream_c["anchor_carrier_name"] == "Crestline Mobility"
    assert stream_v["servicing_status"] == stream_c["servicing_status"] == "PERFORMING"

    facility = create_facility(
        api, portfolio["id"], facility_name="Warehouse L50", carrier_concentration_limit_bps=5000
    )
    pledge_v = create_pledge(api, facility["id"], leg_v.lease_stream_id)
    pledge_c = create_pledge(api, facility["id"], leg_c.lease_stream_id)

    for pledge in (pledge_v, pledge_c):
        assert pledge["valuation_basis_snapshot"] == "MARK_TO_MODEL"
        assert pledge["basis_value_cents"] == VALUE_AT_FIXED_300_BPS, (
            "a mark-to-model pledge takes its basis from the stream's APPROVED valuation"
        )
        assert pledge["haircut_bps"] == 0, "a PERFORMING stream carries a zero haircut"
        assert pledge["eligible_value_cents"] == VALUE_AT_FIXED_300_BPS
        assert_pledge_eligible_value(pledge)

    facility = read_facility(api, facility["id"])
    assert facility["pledged_stream_count"] == 2
    assert facility["pledged_eligible_total_cents"] == 89_254_022
    assert facility["concentration_excess_cents"] == 0, (
        "each carrier's 44627011 total equals the 5000 bps ceiling of 44627011, so nothing is excess"
    )
    assert facility["borrowing_base_cents"] == 58_015_114, (
        f"borrowing_base_cents is {facility['borrowing_base_cents']}, expected 58015114 from "
        "6500 bps of the undeducted 89254022 pool"
    )
    assert facility["compliance_state"] == "COMPLIANT"
    assert_borrowing_base(facility)


def test_shaving_one_basis_point_off_the_concentration_limit_shrinks_the_borrowing_base(api):
    """Dropping the per-carrier limit from 5000 to 4999 bps makes each of the two anchor
    carriers breach the ceiling by 8,925 cents, and the deduction lands before the advance
    rate is applied.

    PRD 3.9: "Third, subtract `concentration_excess_cents` from the gross eligible pool to get the eligible pool after concentration."
    PRD 3.9: "Finally, `borrowing_base_cents` is that concentration-adjusted pool multiplied by `advance_rate_bps`, divided by ten thousand, rounded half up to a whole number of cents."

    Design: Difficulty/combinatorial_formula/facility_borrowing_base_composes_concentration_cap_then_advance_rate
    """
    portfolio, leg_v, leg_c = _two_acquired_streams_under_distinct_anchor_carriers(api)

    facility = create_facility(
        api, portfolio["id"], facility_name="Warehouse L49", carrier_concentration_limit_bps=4999
    )
    create_pledge(api, facility["id"], leg_v.lease_stream_id)
    create_pledge(api, facility["id"], leg_c.lease_stream_id)

    facility = validate_success(
        api.get_financing_facility(facility["id"], headers=make_treasury_officer_headers())
    )
    assert facility["carrier_concentration_limit_bps"] == 4999
    assert facility["pledged_eligible_total_cents"] == 89_254_022
    assert facility["concentration_excess_cents"] == 17_850, (
        f"concentration_excess_cents is {facility['concentration_excess_cents']}, expected 17850 from "
        "two carriers each 8925 above the 44618086 cent ceiling"
    )
    assert facility["borrowing_base_cents"] == 58_003_512, (
        f"borrowing_base_cents is {facility['borrowing_base_cents']}, expected 58003512 from 6500 bps "
        "of the 89236172 cent pool left after the concentration deduction"
    )
    assert facility["compliance_state"] == "COMPLIANT"
    assert_borrowing_base(facility)
