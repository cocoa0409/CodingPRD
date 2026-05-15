"""Auction engine: filtering, ranking, GSP vs VCG pricing, floor
enforcement, bid shading, frequency cap. Covers PRD §3.5 in full.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    accumulate_impressions_for_user,
    approve_creative_end_to_end,
    assert_auction_event,
    create_ad_group,
    create_campaign,
    random_suffix,
    run_auction,
    run_auction_payload,
    setup_active_advertiser,
    setup_active_campaign_with_approved_creative,
    setup_frequency_cap_at_boundary,
    setup_two_ad_groups_for_auction,
    validate_error,
    validate_success,
)


# ===========================================================================
# Empty candidate pool (PRD §3.5)
# ===========================================================================
class TestEmptyAuctionPool:

    def test_empty_candidate_ad_group_ids_rejected(self, api):
        """PRD §3.5: "If candidate_ad_group_ids is empty, the request
        is rejected with ERR_EMPTY_AUCTION_POOL."

        Claim: candidate_ad_group_ids=[] -> ERR_EMPTY_AUCTION_POOL, 400.

        # difficulty: boundary_precision_check/empty_auction_candidate_pool_zero_count_boundary
        """
        res = api.run_auction(
            run_auction_payload(candidate_ad_group_ids=[]),
            TEST_USERS["exchange_service_headers"],
        )
        validate_error(res, ApiErrorId.ERR_EMPTY_AUCTION_POOL.value)

    def test_single_candidate_succeeds_after_empty_pool_rejection(self, api):
        """PRD §3.5: empty pool rejection is local — the system still
        accepts auctions with at least one candidate.

        Claim: pool with one valid candidate returns an AuctionEvent.

        # difficulty: boundary_precision_check/empty_auction_candidate_pool_zero_count_boundary
        """
        setup = setup_active_campaign_with_approved_creative()
        res = api.run_auction(
            run_auction_payload(
                candidate_ad_group_ids=[setup["ad_group"]["id"]],
                floor_price_cents=1,
                pricing_rule="GSP",
            ),
            TEST_USERS["exchange_service_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_auction_event(data)
        assert data["outcome"] == "FILLED"


# ===========================================================================
# Ranking score (PRD §3.5) — three-input non-linear formula
# ===========================================================================
class TestAuctionRanking:

    def test_higher_quality_times_ctr_wins_despite_lower_bid(self, api):
        """PRD §3.5: "The ranking score for the candidate is then the
        product of three terms: the effective bid in cents, the
        candidate's quality_score, and the candidate's predicted_ctr."

        Claim: G1 bid=1000, q=2.0, ctr=0.05 (score=100); G2 bid=200,
        q=8.0, ctr=0.10 (score=160). G2 must win.

        # difficulty: combinatorial_formula/auction_ranking_score_three_input_nonlinear
        """
        setup = setup_two_ad_groups_for_auction(
            g1_kwargs={
                "bid_cents": 1000, "bidding_strategy": "CPC",
                "quality_score": 2.0, "predicted_ctr": 0.05,
            },
            g2_kwargs={
                "bid_cents": 200, "bidding_strategy": "CPC",
                "quality_score": 8.0, "predicted_ctr": 0.10,
            },
        )
        # Run a GSP auction at floor=50.
        res = api.run_auction(
            run_auction_payload(
                candidate_ad_group_ids=[
                    setup["ad_group_1"]["id"], setup["ad_group_2"]["id"],
                ],
                pricing_rule="GSP",
                floor_price_cents=50,
            ),
            TEST_USERS["exchange_service_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["outcome"] == "FILLED"
        assert data["winning_ad_group_id"] == setup["ad_group_2"]["id"], (
            "PRD §3.5: G2 ranking_score=160 > G1=100 — G2 wins despite "
            "lower bid"
        )
        # Clearing price per PRD §3.5 GSP formula:
        # bid-just-to-beat = ceil(runner_up_score / (W.q * W.ctr)) + 1
        # = ceil(100 / (8.0 * 0.10)) + 1 = ceil(125) + 1 = 126.
        # Then clamp: max(floor=50, 126) = 126; min(126, eff_bid=200) = 126.
        assert data["clearing_price_cents"] == 126, (
            f"PRD §3.5 GSP: ceil(100 / 0.8) + 1 = 126, got "
            f"{data['clearing_price_cents']}"
        )

    def test_cpm_effective_bid_is_per_thousand_bid_divided_by_1000(self, api):
        """PRD §3.5: "for the CPM bidding strategy the effective bid in
        cents equals bid_cents divided by 1000, because bid_cents for
        CPM is expressed per thousand impressions."

        Claim: CPM ad-group with bid_cents=10000 -> effective bid per
        impression == 10; ranking_score = 10 * q * ctr. With G1 CPM
        bid=10000 (eff=10), q=10, ctr=1.0 (score=100) and G2 CPC
        bid=5, q=10, ctr=1.0 (score=50), G1 wins.

        # difficulty: combinatorial_formula/auction_ranking_score_three_input_nonlinear
        """
        setup = setup_two_ad_groups_for_auction(
            g1_kwargs={
                "bid_cents": 10000, "bidding_strategy": "CPM",
                "quality_score": 10.0, "predicted_ctr": 1.0,
            },
            g2_kwargs={
                "bid_cents": 5, "bidding_strategy": "CPC",
                "quality_score": 10.0, "predicted_ctr": 1.0,
            },
            initial_recharge_cents=500000,
        )
        res = api.run_auction(
            run_auction_payload(
                candidate_ad_group_ids=[
                    setup["ad_group_1"]["id"], setup["ad_group_2"]["id"],
                ],
                pricing_rule="GSP",
                floor_price_cents=1,
            ),
            TEST_USERS["exchange_service_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["outcome"] == "FILLED"
        assert data["winning_ad_group_id"] == setup["ad_group_1"]["id"], (
            "PRD §3.5 CPM: effective bid 10000/1000=10; ranking_score "
            "100 > 50 — CPM G1 wins"
        )


# ===========================================================================
# GSP vs VCG (PRD §3.5)
# ===========================================================================
class TestGspVsVcg:

    def test_gsp_and_vcg_produce_different_clearing_prices_same_inputs(self, api):
        """PRD §3.5: "Under GSP, if a runner-up exists, the system
        computes the bid-just-to-beat figure — the runner-up's ranking
        score divided by the product of the winner's quality_score and
        predicted_ctr — then rounds that quotient up to the nearest
        whole cent and adds 1, before clamping the result to be at
        least floor_price_cents and at most the winner's effective bid."
        PRD §3.5: "Under VCG, the same externality quotient is rounded
        up to the nearest whole cent — but with no +1 cent adjustment
        and no shading — before being clamped to be at least the floor
        and at most the winner's effective bid."

        Claim: with W ranking_score=500*10*1.0=5000 NOT — use the
        difficulty design scenario: winner bid=500, q=10, ctr=1.0
        (effective_bid=500, score=5000); runner-up bid=300, q=1.0,
        ctr=1.0 (effective_bid=300, score=300). Both winner's
        q*ctr=10. floor=1.
        GSP = ceil(300/10) + 1 = 31. VCG = ceil(300/10) = 30.

        # difficulty: dual_variant_calc/gsp_vs_vcg_clearing_price_on_auction_event
        """
        setup = setup_two_ad_groups_for_auction(
            g1_kwargs={
                "bid_cents": 500, "bidding_strategy": "CPC",
                "quality_score": 10.0, "predicted_ctr": 1.0,
            },
            g2_kwargs={
                "bid_cents": 300, "bidding_strategy": "CPC",
                "quality_score": 1.0, "predicted_ctr": 1.0,
            },
            initial_recharge_cents=500000,
        )
        gids = [setup["ad_group_1"]["id"], setup["ad_group_2"]["id"]]

        gsp = validate_success(
            api.run_auction(
                run_auction_payload(
                    candidate_ad_group_ids=gids,
                    pricing_rule="GSP",
                    floor_price_cents=1,
                ),
                TEST_USERS["exchange_service_headers"],
            ),
            expected_status=201,
        )
        vcg = validate_success(
            api.run_auction(
                run_auction_payload(
                    candidate_ad_group_ids=gids,
                    pricing_rule="VCG",
                    floor_price_cents=1,
                ),
                TEST_USERS["exchange_service_headers"],
            ),
            expected_status=201,
        )
        assert gsp["winning_ad_group_id"] == setup["ad_group_1"]["id"]
        assert vcg["winning_ad_group_id"] == setup["ad_group_1"]["id"]
        assert gsp["clearing_price_cents"] == 31, (
            f"PRD §3.5 GSP: ceil(300/10) + 1 = 31, got "
            f"{gsp['clearing_price_cents']}"
        )
        assert vcg["clearing_price_cents"] == 30, (
            f"PRD §3.5 VCG: ceil(300/10) = 30, got "
            f"{vcg['clearing_price_cents']}"
        )
        assert gsp["clearing_price_cents"] != vcg["clearing_price_cents"]

    def test_gsp_clearing_at_floor_when_no_runner_up(self, api):
        """PRD §3.5: "Under GSP, if no runner-up exists, the unit
        clearing price in cents is exactly the floor_price_cents."

        Claim: single-candidate GSP auction returns clearing_price_cents
        == floor.

        # difficulty: dual_variant_calc/gsp_vs_vcg_clearing_price_on_auction_event
        """
        setup = setup_active_campaign_with_approved_creative(
            bid_cents=1000,
        )
        res = api.run_auction(
            run_auction_payload(
                candidate_ad_group_ids=[setup["ad_group"]["id"]],
                pricing_rule="GSP",
                floor_price_cents=42,
            ),
            TEST_USERS["exchange_service_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["outcome"] == "FILLED"
        assert data["clearing_price_cents"] == 42, (
            f"PRD §3.5: no runner-up -> clearing == floor, got "
            f"{data['clearing_price_cents']}"
        )


# ===========================================================================
# Frequency cap (PRD §3.5)
# ===========================================================================
class TestFrequencyCap:

    def test_at_inclusive_cap_filters_candidate(self, api):
        """PRD §3.5: "When the ad-group's frequency_cap_per_user_per_day
        is non-null, the candidate is excluded when the count of those
        impressions is greater than or equal to the cap; the boundary
        is inclusive, so a count exactly equal to the cap excludes."

        Claim: with cap=2 and exactly 2 prior IMPRESSION billing events
        for the same user, the next auction filters the candidate ->
        AuctionEvent.outcome=ALL_FILTERED.

        # difficulty: boundary_precision_check/frequency_cap_inclusive_threshold
        """
        setup = setup_frequency_cap_at_boundary(cap=2)
        # Next auction with the same user must filter the only candidate.
        res = api.run_auction(
            run_auction_payload(
                candidate_ad_group_ids=[setup["ad_group"]["id"]],
                pricing_rule="GSP",
                floor_price_cents=1,
                user_id=setup["user_id"],
            ),
            TEST_USERS["exchange_service_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["outcome"] == "ALL_FILTERED", (
            f"PRD §3.5: at cap inclusive -> ALL_FILTERED, got "
            f"{data['outcome']!r}"
        )
        assert setup["ad_group"]["id"] in data["filtered_ad_group_ids"]
        assert data["winning_ad_group_id"] in (None, "")

    def test_below_cap_admits_candidate(self, api):
        """PRD §3.5: "a count of cap minus 1 still admits one more
        impression."

        Claim: with cap=3 and exactly 2 prior impressions (cap-1) the
        ad-group is NOT filtered.

        # difficulty: boundary_precision_check/frequency_cap_inclusive_threshold
        """
        setup = setup_active_campaign_with_approved_creative(
            bidding_strategy="CPM",
            bid_cents=1000,
            frequency_cap_per_user_per_day=3,
            initial_recharge_cents=1_000_000,
        )
        user = f"freq-below-{random_suffix(4)}"
        accumulate_impressions_for_user(
            ad_group_id=setup["ad_group"]["id"], user_id=user,
            count=2, advertiser_id=setup["advertiser"]["id"],
        )
        res = api.run_auction(
            run_auction_payload(
                candidate_ad_group_ids=[setup["ad_group"]["id"]],
                pricing_rule="GSP",
                floor_price_cents=1,
                user_id=user,
            ),
            TEST_USERS["exchange_service_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["outcome"] == "FILLED", (
            f"PRD §3.5: at cap-1 -> still eligible, got "
            f"{data['outcome']!r}"
        )
        assert data["winning_ad_group_id"] == setup["ad_group"]["id"]


# ===========================================================================
# Bid shading (PRD §3.5)
# ===========================================================================
class TestBidShading:

    def test_external_rtb_gsp_applies_shading(self, api):
        """PRD §3.5: "Bid-shading applies only to EXTERNAL_RTB exchanges
        running GSP. After floor enforcement, the clearing unit price
        is multiplied by the shading factor of 0.92 and the result is
        rounded down to a whole cent; bid_shaded is set to true."

        Claim: EXTERNAL_RTB + GSP single-candidate auction at floor=100
        -> clearing_price_cents = floor(100 * 0.92) = 92,
        bid_shaded=true.
        """
        setup = setup_active_campaign_with_approved_creative(bid_cents=1000)
        res = api.run_auction(
            run_auction_payload(
                candidate_ad_group_ids=[setup["ad_group"]["id"]],
                pricing_rule="GSP",
                floor_price_cents=100,
                exchange="EXTERNAL_RTB",
            ),
            TEST_USERS["exchange_service_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["outcome"] == "FILLED"
        assert data["bid_shaded"] is True
        assert data["clearing_price_cents"] == 92, (
            f"PRD §3.5: floor(100 * 0.92) = 92, got "
            f"{data['clearing_price_cents']}"
        )

    def test_internal_auction_does_not_apply_shading(self, api):
        """PRD §3.5: "Internal-inventory auctions and any VCG auctions
        are never shaded."

        Claim: INTERNAL + GSP -> bid_shaded=false; clearing equals
        floor when no runner-up.
        """
        setup = setup_active_campaign_with_approved_creative(bid_cents=1000)
        res = api.run_auction(
            run_auction_payload(
                candidate_ad_group_ids=[setup["ad_group"]["id"]],
                pricing_rule="GSP",
                floor_price_cents=100,
                exchange="INTERNAL",
            ),
            TEST_USERS["exchange_service_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["bid_shaded"] is False
        assert data["clearing_price_cents"] == 100

    def test_vcg_external_rtb_does_not_apply_shading(self, api):
        """PRD §3.5: "Internal-inventory auctions and any VCG auctions
        are never shaded."

        Claim: VCG + EXTERNAL_RTB -> bid_shaded=false.
        """
        setup = setup_active_campaign_with_approved_creative(bid_cents=1000)
        res = api.run_auction(
            run_auction_payload(
                candidate_ad_group_ids=[setup["ad_group"]["id"]],
                pricing_rule="VCG",
                floor_price_cents=100,
                exchange="EXTERNAL_RTB",
            ),
            TEST_USERS["exchange_service_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["bid_shaded"] is False
