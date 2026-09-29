"""Just-inside and just-outside probes of the four money-and-score cuts that decide a buyout:
the discount tier a tenancy roster earns, the utilization at which a capital pool freezes, the
broker tier a gross consideration falls into, and the bid ceiling an offer may touch but not pass.
"""

from test_helpers import (
    ApiErrorId,
    CapitalPosture,
    CarrierCreditTier,
    EscalatorType,
    OfferStatus,
    OfferType,
    TenancyStatus,
    TenancyType,
    ValuationMethod,
    adjust_capital,
    assert_max_bid_ceiling,
    assert_settlement_arithmetic,
    assert_utilization_and_posture,
    bps_of,
    build_asset_graph,
    build_chain,
    build_two_deals_on_one_portfolio,
    create_valuation,
    make_acquisition_analyst_headers,
    make_platform_admin_headers,
    read_lease_stream,
    set_tenancy_status,
    validate_error,
    validate_paginated,
    validate_success,
)

# One rent stream, priced two ways: the only thing that ever differs between the paired
# streams below is the tenancy roster, so the discount tier is the sole moving part.
IDENTICAL_ECONOMICS = {
    "current_annual_rent_cents": 3_600_000,
    "escalator_type": EscalatorType.FIXED_PCT.value,
    "escalator_pct_bps": 300,
    "remaining_term_months": 180,
}

# The PRD's own per-year walk, recomputed by hand: 40 modelled years of 3,600,000 cents
# growing at 300 bps, each year discounted and half-up rounded before the summation, with
# the 2000 bps renewal haircut on years beyond the 15 contracted ones (180 // 12).
VALUE_AT_850_BPS = 52_919_246
VALUE_AT_1000_BPS = 44_627_011
TIER_STEP_CENTS = 8_292_235
MAX_BID_AT_1000_BPS = 46_858_362


def _stream_scoring_exactly_sixty(api):
    """One investment-grade anchor at 40.00 plus two speculative anchors at 10.00 each."""
    return build_asset_graph(
        api,
        tower_company={"legal_name": "Summit Towers LLC", "notice_email": "rofr@summit.example"},
        tower_site={"site_code": "NE-6001"},
        landowner={"legal_name": "Owner_60 LLC", "contact_email": "owner_60@x.example"},
        lease_stream=dict(IDENTICAL_ECONOMICS),
        tenancies=[
            {
                "carrier_name": "Vantage Wireless",
                "carrier_credit_tier": CarrierCreditTier.INVESTMENT_GRADE.value,
                "tenancy_type": TenancyType.ANCHOR.value,
                "monthly_rent_share_cents": 250_000,
            },
            {
                "carrier_name": "Bluewave Mobile",
                "carrier_credit_tier": CarrierCreditTier.SPECULATIVE.value,
                "tenancy_type": TenancyType.ANCHOR.value,
                "monthly_rent_share_cents": 120_000,
            },
            {
                "carrier_name": "Ridgeline Cellular",
                "carrier_credit_tier": CarrierCreditTier.SPECULATIVE.value,
                "tenancy_type": TenancyType.ANCHOR.value,
                "monthly_rent_share_cents": 110_000,
            },
        ],
    )


def _stream_scoring_fifty_nine(api, *, site_code="NE-6002"):
    """An investment-grade anchor at 40.00 plus a holdover colocation at 24.00 less 5 = 19.00."""
    scenario = build_asset_graph(
        api,
        tower_company={"legal_name": "Crestline Towers LLC", "notice_email": "rofr@crestline.example"},
        tower_site={"site_code": site_code},
        landowner={"legal_name": "Owner_59 LLC", "contact_email": "owner_59@x.example"},
        lease_stream=dict(IDENTICAL_ECONOMICS),
        tenancies=[
            {
                "carrier_name": "Vantage Wireless",
                "carrier_credit_tier": CarrierCreditTier.INVESTMENT_GRADE.value,
                "tenancy_type": TenancyType.ANCHOR.value,
                "monthly_rent_share_cents": 250_000,
            },
            {
                "carrier_name": "Crestline Mobility",
                "carrier_credit_tier": CarrierCreditTier.INVESTMENT_GRADE.value,
                "tenancy_type": TenancyType.COLOCATION.value,
                "monthly_rent_share_cents": 90_000,
            },
        ],
    )
    scenario["holdover_tenancy"] = set_tenancy_status(
        api, scenario["tenancies"][1]["id"], TenancyStatus.HOLDOVER.value
    )
    return scenario


# ===========================================================================
# The >= 60 discount tier: a roster scoring exactly 60 against one scoring 59
# ===========================================================================


def test_roster_scoring_exactly_sixty_prices_at_the_eight_hundred_fifty_basis_point_tier(api):
    """A stream whose active roster sums to exactly 60 quality points lands on the 850 bps
    tier, and its perpetual value is the sum of forty individually rounded discounted years.

    PRD 3.3: The stream's `tenancy_quality_score` is then the sum of the **two-decimal figures produced at step five** — not the sum of the whole-number `quality_points` values written onto the tenancies — with that sum rounded half up to a whole number and finally clamped into the inclusive range from zero to one hundred.
    PRD 3.4: That snapshot picks the base discount tier from a four-rung ladder evaluated from the top down: a score of 80 or more prices at 700 basis points; failing that, a score of 60 or more prices at 850; failing that, a score of 40 or more prices at 1000; and anything below 40 prices at 1250.
    PRD 3.4: Because the ladder is evaluated top down with inclusive thresholds, a score of exactly 60 lands on 850 while a score of 59 falls through to 1000 — a one-point difference in tenancy quality that moves the price materially.
    PRD 3.4: `value_cents` is the sum of those rounded per-year figures.

    Design: Difficulty/boundary_precision_check/discount_tier_boundary_score_60_versus_59
    """
    scenario = _stream_scoring_exactly_sixty(api)

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["tenancy_quality_score"] == 60, (
        f"a 40.00 anchor plus two 10.00 anchors must score exactly 60, got {stream['tenancy_quality_score']}"
    )
    assert stream["active_tenancy_count"] == 3

    valuation = create_valuation(api, scenario.lease_stream_id, method=ValuationMethod.LUMP_SUM_PERPETUAL.value)
    assert valuation["tenancy_quality_score_snapshot"] == 60
    assert valuation["discount_rate_bps"] == 850, (
        f"a score of exactly 60 is inclusive of the 850 bps rung, got {valuation['discount_rate_bps']}"
    )
    assert valuation["growth_rate_bps"] == 300
    assert valuation["horizon_years"] == 40
    assert valuation["value_cents"] == VALUE_AT_850_BPS, (
        f"value_cents is {valuation['value_cents']}, expected {VALUE_AT_850_BPS} at 850 bps"
    )
    assert_max_bid_ceiling(valuation)


def test_roster_scoring_fifty_nine_falls_through_to_the_one_thousand_basis_point_tier(api):
    """A holdover colocation drops the same asset one quality point below the tier cut, so the
    identical rent stream is discounted at 1000 bps instead of 850.

    PRD 3.3: If the tenancy's `status` is `HOLDOVER`, subtract five points from the rounded figure as a holdover penalty.
    PRD 3.3: Store on the tenancy, as its `quality_points`, that same figure rounded half up to a whole number.
    PRD 3.4: Because the ladder is evaluated top down with inclusive thresholds, a score of exactly 60 lands on 850 while a score of 59 falls through to 1000 — a one-point difference in tenancy quality that moves the price materially.
    PRD 3.4: The year's present value is then rounded half up to a whole number of cents.

    Design: Difficulty/boundary_precision_check/discount_tier_boundary_score_60_versus_59
    """
    scenario = _stream_scoring_fifty_nine(api)

    holdover = scenario["holdover_tenancy"]
    assert holdover["status"] == TenancyStatus.HOLDOVER.value
    assert holdover["quality_points"] == 19, (
        f"40 points at the 0.6 colocation multiplier is 24.00, less the 5 point penalty is 19, "
        f"got {holdover['quality_points']}"
    )

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["tenancy_quality_score"] == 59, (
        f"40.00 plus 19.00 must score 59, got {stream['tenancy_quality_score']}"
    )

    valuation = create_valuation(api, scenario.lease_stream_id, method=ValuationMethod.LUMP_SUM_PERPETUAL.value)
    assert valuation["tenancy_quality_score_snapshot"] == 59
    assert valuation["discount_rate_bps"] == 1000, (
        f"a score of 59 falls through the 60 rung to 1000 bps, got {valuation['discount_rate_bps']}"
    )
    assert valuation["value_cents"] == VALUE_AT_1000_BPS, (
        f"value_cents is {valuation['value_cents']}, expected {VALUE_AT_1000_BPS} at 1000 bps"
    )
    assert_max_bid_ceiling(valuation)


def test_single_quality_point_across_the_sixty_cut_moves_perpetual_value_by_a_fixed_step(api):
    """Two streams with identical rent, escalator and remaining term differ by one quality point,
    and that single point is worth 8,292,235 cents of model value.

    PRD 3.4: Because the ladder is evaluated top down with inclusive thresholds, a score of exactly 60 lands on 850 while a score of 59 falls through to 1000 — a one-point difference in tenancy quality that moves the price materially.
    PRD 3.4: The rounding order in both variants is pinned: each year's present value is rounded before the summation, and the prepaid haircut is applied once to the finished sum.

    Design: Difficulty/boundary_precision_check/discount_tier_boundary_score_60_versus_59
    """
    inside = _stream_scoring_exactly_sixty(api)
    outside = _stream_scoring_fifty_nine(api)

    valuation_inside = create_valuation(
        api, inside.lease_stream_id, method=ValuationMethod.LUMP_SUM_PERPETUAL.value
    )
    valuation_outside = create_valuation(
        api, outside.lease_stream_id, method=ValuationMethod.LUMP_SUM_PERPETUAL.value
    )

    assert (valuation_inside["tenancy_quality_score_snapshot"], valuation_outside["tenancy_quality_score_snapshot"]) == (60, 59)
    assert (valuation_inside["discount_rate_bps"], valuation_outside["discount_rate_bps"]) == (850, 1000)
    assert valuation_inside["value_cents"] - valuation_outside["value_cents"] == TIER_STEP_CENTS, (
        f"the one-point step is {valuation_inside['value_cents'] - valuation_outside['value_cents']}, "
        f"expected {TIER_STEP_CENTS}"
    )


# ===========================================================================
# The >= 9000 bps freeze rung: 8998 bps against exactly 9000 bps
# ===========================================================================


def test_utilization_of_8998_basis_points_leaves_the_capital_pool_constrained(api):
    """Shrinking the pool until utilization rounds to 8998 bps keeps the posture two basis points
    short of the freeze rung, so the pool is only CONSTRAINED.

    PRD 3.1: Utilization is measured against the whole pool: let *used* be the sum of `committed_capital_cents` and `deployed_capital_cents`; then `utilization_bps` is zero when `total_capital_cents` is zero, and otherwise is *used* multiplied by ten thousand, divided by `total_capital_cents`, and rounded half up to a whole number of basis points.
    PRD 3.1: Posture follows utilization through a two-rung ladder evaluated from the top: when `utilization_bps` is at or above 9000 — that is, ninety percent of the pool or more is spoken for — `capital_posture` is `FROZEN`; otherwise, when `utilization_bps` is at or above 7500, it is `CONSTRAINED`; otherwise it is `OPEN`.

    Design: Difficulty/boundary_precision_check/portfolio_posture_boundary_utilization_8998_then_exactly_9000
    """
    scenario = build_chain(api, "offer_accepted", portfolio={"total_capital_cents": 50_000_000})

    opening = validate_success(api.get_portfolio(scenario.portfolio_id, headers=make_platform_admin_headers()))
    assert opening["committed_capital_cents"] == 36_540_000, (
        f"a 36,000,000 cent gross plus a 540,000 cent broker fee reserves 36,540,000, "
        f"got {opening['committed_capital_cents']}"
    )
    assert opening["utilization_bps"] == 7308
    assert opening["capital_posture"] == CapitalPosture.OPEN.value
    assert opening["available_capital_cents"] == 13_460_000

    shrunk = adjust_capital(api, scenario.portfolio_id, -9_390_000, memo="First tranche returned to investors")
    assert shrunk["total_capital_cents"] == 40_610_000
    assert shrunk["utilization_bps"] == 8998, (
        f"36,540,000 of 40,610,000 rounds half up to 8998 bps, got {shrunk['utilization_bps']}"
    )
    assert shrunk["capital_posture"] == CapitalPosture.CONSTRAINED.value, (
        f"8998 bps is below the 9000 bps freeze rung, so the posture must be CONSTRAINED, "
        f"got {shrunk['capital_posture']}"
    )
    assert shrunk["available_capital_cents"] == 4_070_000
    assert_utilization_and_posture(shrunk)


def test_utilization_landing_on_exactly_9000_basis_points_freezes_the_capital_pool(api):
    """A further 10,000 cent withdrawal puts utilization on exactly 9000 bps, which the PRD makes
    inclusive, so the pool freezes.

    PRD 3.1: Posture follows utilization through a two-rung ladder evaluated from the top: when `utilization_bps` is at or above 9000 — that is, ninety percent of the pool or more is spoken for — `capital_posture` is `FROZEN`; otherwise, when `utilization_bps` is at or above 7500, it is `CONSTRAINED`; otherwise it is `OPEN`.
    PRD 3.1: Both rungs are inclusive, so a portfolio sitting at exactly 9000 basis points is frozen and one sitting at exactly 7500 is constrained.
    PRD 3.1: At every moment the three balances must add back to the whole: `available_capital_cents` plus `committed_capital_cents` plus `deployed_capital_cents` equals `total_capital_cents`.

    Design: Difficulty/boundary_precision_check/portfolio_posture_boundary_utilization_8998_then_exactly_9000
    """
    scenario = build_chain(api, "offer_accepted", portfolio={"total_capital_cents": 50_000_000})

    adjust_capital(api, scenario.portfolio_id, -9_390_000, memo="First tranche returned to investors")
    frozen = adjust_capital(api, scenario.portfolio_id, -10_000, memo="Residual tranche returned to investors")

    assert frozen["total_capital_cents"] == 40_600_000
    assert frozen["committed_capital_cents"] == 36_540_000
    assert frozen["utilization_bps"] == 9000, (
        f"36,540,000 of 40,600,000 is exactly 9000 bps, got {frozen['utilization_bps']}"
    )
    assert frozen["capital_posture"] == CapitalPosture.FROZEN.value, (
        f"exactly 9000 bps is inclusive of the freeze rung, got {frozen['capital_posture']}"
    )
    assert frozen["available_capital_cents"] == 4_060_000
    assert_utilization_and_posture(frozen)


# ===========================================================================
# The >= 30,000,000 cent broker tier: exactly at the tier against one cent below
# ===========================================================================


def test_gross_of_exactly_thirty_million_cents_takes_the_one_hundred_fifty_basis_point_broker_tier(api):
    """A gross consideration sitting exactly on the top broker rung is charged 150 bps, so the
    fee is 450,000 cents and the commitment 30,450,000.

    PRD 3.7: The broker tier is keyed on **gross**, on a ladder evaluated from the top: a gross at or above 30,000,000 cents — three hundred thousand dollars — sets `broker_fee_bps` to 150; failing that, a gross at or above 10,000,000 cents — one hundred thousand dollars — sets it to 200; anything below that sets it to 250.
    PRD 3.7: `broker_fee_cents` is gross multiplied by `broker_fee_bps`, divided by ten thousand, rounded half up to a whole number of cents.
    PRD 3.7: `net_landowner_proceeds_cents` is gross less `holdback_cents`, and `total_commitment_cents` — the figure the portfolio actually has to set aside — is gross plus `broker_fee_cents`.

    Design: Difficulty/boundary_precision_check/broker_fee_tier_boundary_gross_exactly_30000000_versus_one_cent_below
    """
    pair = build_two_deals_on_one_portfolio(
        api,
        milestone="offer_accepted",
        total_capital_cents=100_000_000,
        offers=[{"amount_cents": 30_000_000}, {"amount_cents": 29_999_999}],
    )

    settlement = validate_success(
        api.get_settlement(pair.deal_a.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert settlement["agreed_consideration_cents"] == 30_000_000
    assert settlement["broker_fee_bps"] == 150, (
        f"a gross of exactly 30,000,000 is inclusive of the 150 bps rung, got {settlement['broker_fee_bps']}"
    )
    assert settlement["broker_fee_cents"] == 450_000 == bps_of(30_000_000, 150)
    assert settlement["holdback_cents"] == 0
    assert settlement["net_landowner_proceeds_cents"] == 30_000_000
    assert settlement["total_commitment_cents"] == 30_450_000
    assert_settlement_arithmetic(settlement, expected_open_dispute_count=0)


def test_gross_one_cent_below_thirty_million_falls_to_the_two_hundred_basis_point_broker_tier(api):
    """One cent under the rung the gross drops to 200 bps, and the fee rounds half up from
    599,999.98 to 600,000 cents.

    PRD 3.7: The broker tier is keyed on **gross**, on a ladder evaluated from the top: a gross at or above 30,000,000 cents — three hundred thousand dollars — sets `broker_fee_bps` to 150; failing that, a gross at or above 10,000,000 cents — one hundred thousand dollars — sets it to 200; anything below that sets it to 250.
    PRD 3.7: `broker_fee_cents` is gross multiplied by `broker_fee_bps`, divided by ten thousand, rounded half up to a whole number of cents.

    Design: Difficulty/boundary_precision_check/broker_fee_tier_boundary_gross_exactly_30000000_versus_one_cent_below
    """
    pair = build_two_deals_on_one_portfolio(
        api,
        milestone="offer_accepted",
        total_capital_cents=100_000_000,
        offers=[{"amount_cents": 30_000_000}, {"amount_cents": 29_999_999}],
    )

    settlement = validate_success(
        api.get_settlement(pair.deal_b.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert settlement["agreed_consideration_cents"] == 29_999_999
    assert settlement["broker_fee_bps"] == 200, (
        f"a gross of 29,999,999 misses the 30,000,000 rung and takes 200 bps, "
        f"got {settlement['broker_fee_bps']}"
    )
    assert settlement["broker_fee_cents"] == 600_000 == bps_of(29_999_999, 200), (
        f"29,999,999 at 200 bps is 599,999.98 and rounds half up to 600,000, "
        f"got {settlement['broker_fee_cents']}"
    )
    assert settlement["holdback_cents"] == 0
    assert settlement["net_landowner_proceeds_cents"] == 29_999_999
    assert settlement["total_commitment_cents"] == 30_599_999
    assert_settlement_arithmetic(settlement, expected_open_dispute_count=0)


def test_one_cent_less_gross_costs_the_portfolio_more_across_the_broker_tier_cut(api):
    """Because the tier is keyed on gross, the cheaper purchase carries the larger broker fee and
    the larger commitment against the same capital pool.

    PRD 3.7: The order of that computation is pinned: the broker tier is selected on gross, then the fee is computed, then the holdback, then the net.
    PRD 3.7: Selecting the broker tier on gross-less-holdback is a different and incorrect answer, and a deal straddling a tier boundary will expose the difference.
    PRD 3.1: `committed_capital_cents` is the sum of `total_commitment_cents` across deals whose `capital_state` is `RESERVED` or `ESCROWED`.

    Design: Difficulty/boundary_precision_check/broker_fee_tier_boundary_gross_exactly_30000000_versus_one_cent_below
    """
    pair = build_two_deals_on_one_portfolio(
        api,
        milestone="offer_accepted",
        total_capital_cents=100_000_000,
        offers=[{"amount_cents": 30_000_000}, {"amount_cents": 29_999_999}],
    )

    at_tier = validate_success(
        api.get_settlement(pair.deal_a.deal_id, headers=make_acquisition_analyst_headers())
    )
    below_tier = validate_success(
        api.get_settlement(pair.deal_b.deal_id, headers=make_acquisition_analyst_headers())
    )

    assert below_tier["agreed_consideration_cents"] == at_tier["agreed_consideration_cents"] - 1
    assert below_tier["broker_fee_cents"] - at_tier["broker_fee_cents"] == 150_000, (
        f"the one cent step must cost 150,000 cents more in fees, got "
        f"{below_tier['broker_fee_cents'] - at_tier['broker_fee_cents']}"
    )
    assert below_tier["total_commitment_cents"] > at_tier["total_commitment_cents"]

    portfolio = validate_success(
        api.get_portfolio(pair.portfolio_id, headers=make_platform_admin_headers())
    )
    assert portfolio["committed_capital_cents"] == 30_450_000 + 30_599_999
    assert portfolio["utilization_bps"] == 6105
    assert portfolio["capital_posture"] == CapitalPosture.OPEN.value
    assert_utilization_and_posture(portfolio)


# ===========================================================================
# The <= max_bid_cents guardrail: an offer exactly at the ceiling, then one cent over
# ===========================================================================


def test_offer_exactly_equal_to_the_max_bid_ceiling_is_sent(api):
    """An offer priced at exactly 105 percent of model value sits on the inclusive side of the
    guardrail and sends, consuming the deal's first negotiation round.

    PRD 3.4: `max_bid_cents` is `value_cents` multiplied by 10500 basis points divided by ten thousand — one hundred five percent of model value — rounded half up to a whole number of cents.
    PRD 2.8: **Offer within the bid guardrail** — the offer's `amount_cents` is less than or equal to the pinned valuation's `max_bid_cents`; otherwise `ERR_OFFER_EXCEEDS_GUARDRAIL` (422).
    PRD 3.5: Sending stamps `sent_at` from the current instant, increments the deal's `negotiation_rounds` and then copies the new count into the offer's `round_number`, moves the deal `OUTREACH → NEGOTIATION`, and lifts the landowner's `outreach_status` from `NEW` to `CONTACTED` if it was still `NEW`.

    Design: Difficulty/boundary_precision_check/offer_guardrail_boundary_amount_equal_to_max_bid_then_one_cent_over
    """
    scenario = build_chain(api, "outreach", lease_stream=dict(IDENTICAL_ECONOMICS))

    valuation = scenario["valuation"]
    assert valuation["value_cents"] == VALUE_AT_1000_BPS
    assert valuation["max_bid_cents"] == MAX_BID_AT_1000_BPS, (
        f"max_bid_cents is {valuation['max_bid_cents']}, expected {MAX_BID_AT_1000_BPS}"
    )
    assert_max_bid_ceiling(valuation)

    offer = validate_success(
        api.create_offer(
            scenario.deal_id,
            {
                "offer_type": OfferType.LUMP_SUM.value,
                "amount_cents": MAX_BID_AT_1000_BPS,
                "expires_at": "2026-12-31T00:00:00Z",
            },
            headers=make_acquisition_analyst_headers(),
        ),
        201,
    )
    sent = validate_success(
        api.transition_offer(offer["id"], {"action": "SEND"}, headers=make_acquisition_analyst_headers())
    )
    assert sent["status"] == OfferStatus.SENT.value, (
        f"an amount equal to max_bid_cents is within the guardrail, got status {sent['status']}"
    )
    assert sent["amount_cents"] == MAX_BID_AT_1000_BPS
    assert sent["round_number"] == 1

    deal = validate_success(api.get_deal(scenario.deal_id, headers=make_acquisition_analyst_headers()))
    assert deal["negotiation_rounds"] == 1


def test_offer_one_cent_above_the_max_bid_ceiling_is_refused(api):
    """Raising the same offer by a single cent puts it outside the guardrail, and the send is
    refused rather than trimmed.

    PRD 2.8: **Offer within the bid guardrail** — the offer's `amount_cents` is less than or equal to the pinned valuation's `max_bid_cents`; otherwise `ERR_OFFER_EXCEEDS_GUARDRAIL` (422).
    PRD 3.4: That five percent of headroom above model is the entire discretionary room the negotiating team has, and it is enforced mechanically: no offer may ever exceed it.

    Design: Difficulty/boundary_precision_check/offer_guardrail_boundary_amount_equal_to_max_bid_then_one_cent_over
    """
    scenario = build_chain(api, "outreach", lease_stream=dict(IDENTICAL_ECONOMICS))
    assert scenario["valuation"]["max_bid_cents"] == MAX_BID_AT_1000_BPS

    at_ceiling = validate_success(
        api.create_offer(
            scenario.deal_id,
            {
                "offer_type": OfferType.LUMP_SUM.value,
                "amount_cents": MAX_BID_AT_1000_BPS,
                "expires_at": "2026-12-31T00:00:00Z",
            },
            headers=make_acquisition_analyst_headers(),
        ),
        201,
    )
    validate_success(
        api.transition_offer(at_ceiling["id"], {"action": "SEND"}, headers=make_acquisition_analyst_headers())
    )
    withdrawn = validate_success(
        api.transition_offer(at_ceiling["id"], {"action": "WITHDRAW"}, headers=make_acquisition_analyst_headers())
    )
    assert withdrawn["status"] == OfferStatus.WITHDRAWN.value

    over_ceiling = validate_success(
        api.create_offer(
            scenario.deal_id,
            {
                "offer_type": OfferType.LUMP_SUM.value,
                "amount_cents": MAX_BID_AT_1000_BPS + 1,
                "expires_at": "2026-12-31T00:00:00Z",
            },
            headers=make_acquisition_analyst_headers(),
        ),
        201,
    )
    validate_error(
        api.transition_offer(over_ceiling["id"], {"action": "SEND"}, headers=make_acquisition_analyst_headers()),
        ApiErrorId.ERR_OFFER_EXCEEDS_GUARDRAIL.value,
    )

    offers, _meta = validate_paginated(
        api.list_offers(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    over = next(item for item in offers if item["id"] == over_ceiling["id"])
    assert over["status"] == OfferStatus.DRAFT.value, (
        f"a refused send leaves the offer in DRAFT, got {over['status']}"
    )
    assert over.get("sent_at") is None


def test_refused_over_ceiling_send_consumes_no_negotiation_round(api):
    """Only a successful send advances the round counter, so the deal that sent one compliant
    offer and one over-ceiling offer still sits at a single consumed round.

    PRD 3.5: Sending stamps `sent_at` from the current instant, increments the deal's `negotiation_rounds` and then copies the new count into the offer's `round_number`, moves the deal `OUTREACH → NEGOTIATION`, and lifts the landowner's `outreach_status` from `NEW` to `CONTACTED` if it was still `NEW`.
    PRD 2.8: **Offer within the bid guardrail** — the offer's `amount_cents` is less than or equal to the pinned valuation's `max_bid_cents`; otherwise `ERR_OFFER_EXCEEDS_GUARDRAIL` (422).

    Design: Difficulty/boundary_precision_check/offer_guardrail_boundary_amount_equal_to_max_bid_then_one_cent_over
    """
    scenario = build_chain(api, "outreach", lease_stream=dict(IDENTICAL_ECONOMICS))

    at_ceiling = validate_success(
        api.create_offer(
            scenario.deal_id,
            {
                "offer_type": OfferType.LUMP_SUM.value,
                "amount_cents": MAX_BID_AT_1000_BPS,
                "expires_at": "2026-12-31T00:00:00Z",
            },
            headers=make_acquisition_analyst_headers(),
        ),
        201,
    )
    validate_success(
        api.transition_offer(at_ceiling["id"], {"action": "SEND"}, headers=make_acquisition_analyst_headers())
    )
    validate_success(
        api.transition_offer(at_ceiling["id"], {"action": "WITHDRAW"}, headers=make_acquisition_analyst_headers())
    )

    over_ceiling = validate_success(
        api.create_offer(
            scenario.deal_id,
            {
                "offer_type": OfferType.LUMP_SUM.value,
                "amount_cents": MAX_BID_AT_1000_BPS + 1,
                "expires_at": "2026-12-31T00:00:00Z",
            },
            headers=make_acquisition_analyst_headers(),
        ),
        201,
    )
    validate_error(
        api.transition_offer(over_ceiling["id"], {"action": "SEND"}, headers=make_acquisition_analyst_headers()),
        ApiErrorId.ERR_OFFER_EXCEEDS_GUARDRAIL.value,
    )

    deal = validate_success(api.get_deal(scenario.deal_id, headers=make_acquisition_analyst_headers()))
    assert deal["negotiation_rounds"] == 1, (
        f"the refused send must not consume a round, got negotiation_rounds {deal['negotiation_rounds']}"
    )
