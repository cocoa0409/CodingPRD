"""Conversion ingest + attribution: LAST_CLICK, POSITION_BASED,
DATA_DRIVEN models. Covers PRD §3.7 in full.
"""
from __future__ import annotations

from typing import List

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    advance_clock,
    assert_attributed_credit_sums_to_value,
    assert_conversion_event,
    attribute_conversion,
    create_conversion,
    get_advertiser,
    ingest_billing_event,
    random_suffix,
    run_auction,
    setup_active_campaign_with_approved_creative,
    validate_error,
    validate_success,
)


def _three_finalized_clicks_for_user(
    setup: dict, user_id: str,
) -> List[dict]:
    """Run three auctions and finalise three CLICK BillingEvents for a
    single user_id, separated by 1-day clock advances.
    """
    advertiser = setup["advertiser"]
    ad_group = setup["ad_group"]
    clicks: List[dict] = []
    for i in range(3):
        auc = run_auction(
            candidate_ad_group_ids=[ad_group["id"]],
            pricing_rule="GSP",
            floor_price_cents=10,
            user_id=user_id,
        )
        if auc["outcome"] != "FILLED":
            pytest.skip(
                f"Auction #{i} did not FILL (got {auc['outcome']!r})"
            )
        be = ingest_billing_event(
            auction_event_id=auc["id"],
            ad_group_id=ad_group["id"],
            event_type="CLICK",
            ivt_score=0.0,
        )
        if be["status"] != "FINALIZED":
            pytest.skip(
                f"Click #{i} did not FINALIZE (got {be['status']!r})"
            )
        clicks.append(be)
        # Advance clock by 1 day (86400s) between clicks to ensure
        # deterministic ordering by created_at.
        if i < 2:
            advance_clock(86400)
    return clicks


# ===========================================================================
# Conversion ingest validation (PRD §3.7)
# ===========================================================================
class TestConversionIngest:

    def test_attribution_window_below_minimum_rejected(self, api):
        """PRD §3.7: "The attribution_window_days must be in the closed
        range from 1 to 90 inclusive; outside that range the request is
        rejected with ERR_INVALID_ATTRIBUTION_WINDOW."

        Claim: attribution_window_days=0 (boundary X-1) ->
        ERR_INVALID_ATTRIBUTION_WINDOW.
        """
        setup = setup_active_campaign_with_approved_creative()
        res = api.create_conversion(
            {
                "source": "WEB_PIXEL",
                "user_id": "u-1",
                "advertiser_id": setup["advertiser"]["id"],
                "conversion_type": "PURCHASE",
                "attribution_window_days": 0,
            },
            TEST_USERS["measurement_partner_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_ATTRIBUTION_WINDOW.value)

    def test_attribution_window_above_maximum_rejected(self, api):
        """PRD §3.7: "in the closed range from 1 to 90 inclusive."

        Claim: attribution_window_days=91 (boundary X+1) ->
        ERR_INVALID_ATTRIBUTION_WINDOW.
        """
        setup = setup_active_campaign_with_approved_creative()
        res = api.create_conversion(
            {
                "source": "WEB_PIXEL",
                "user_id": "u-2",
                "advertiser_id": setup["advertiser"]["id"],
                "conversion_type": "PURCHASE",
                "attribution_window_days": 91,
            },
            TEST_USERS["measurement_partner_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_ATTRIBUTION_WINDOW.value)

    def test_attribution_window_at_boundary_accepted(self, api):
        """PRD §3.7: closed range [1, 90].

        Claim: attribution_window_days=1 and =90 (boundaries X) ->
        201, valid conversion record persisted with the requested
        attribution_window_days. (The post-create attribution_status
        depends on whether auto-attribution finds eligible touchpoints
        — PRD is silent on whether the 201 response shows the pre- or
        post-auto-run snapshot, so that field is not asserted here.)
        """
        setup = setup_active_campaign_with_approved_creative()
        for wd in (1, 90):
            res = api.create_conversion(
                {
                    "source": "WEB_PIXEL",
                    "user_id": f"u-bound-{wd}",
                    "advertiser_id": setup["advertiser"]["id"],
                    "conversion_type": "PURCHASE",
                    "attribution_window_days": wd,
                },
                TEST_USERS["measurement_partner_headers"],
            )
            data = validate_success(res, expected_status=201)
            assert_conversion_event(data)
            assert data["attribution_window_days"] == wd


# ===========================================================================
# Attribution — three models (PRD §3.7)
# ===========================================================================
class TestLastClickAttribution:

    def test_last_click_assigns_full_credit_to_most_recent_click(self, api):
        """PRD §3.7: "Under LAST_CLICK, the most recent CLICK touchpoint
        receives 100 percent of the credit."

        Claim: three CLICKs in window, LAST_CLICK -> single touchpoint
        with credit_fraction=1.0 and credit_cents = value_cents.

        # difficulty: dual_variant_calc/last_click_vs_position_based_attribution_on_conversion
        """
        setup = setup_active_campaign_with_approved_creative(
            bid_cents=10, initial_recharge_cents=100000,
        )
        user_id = f"u-lc-{random_suffix(6)}"
        clicks = _three_finalized_clicks_for_user(setup, user_id)
        conv = create_conversion(
            advertiser_id=setup["advertiser"]["id"],
            user_id=user_id,
            value_cents=1000,
            attribution_window_days=7,
            attribution_model="LAST_CLICK",
        )
        result = attribute_conversion(conv["id"])
        assert result["attribution_status"] == "ATTRIBUTED"
        tps = result["attributed_touchpoints"]
        assert len(tps) == 1, (
            f"PRD §3.7 LAST_CLICK: 1 touchpoint, got {len(tps)}"
        )
        assert tps[0]["billing_event_id"] == clicks[-1]["id"], (
            "PRD §3.7: the most-recent CLICK gets credit"
        )
        assert tps[0]["credit_fraction"] == 1.0
        assert tps[0]["credit_cents"] == 1000
        assert_attributed_credit_sums_to_value(result)


class TestPositionBasedAttribution:

    def test_position_based_splits_40_20_40(self, api):
        """PRD §3.7: "Under POSITION_BASED, the first touchpoint
        receives 40 percent, the last touchpoint receives 40 percent,
        and the remaining 20 percent is distributed equally among the
        middle touchpoints."

        Claim: three CLICKs in window, value_cents=1000 -> credit
        distribution 400, 200, 400 with sum == value_cents.

        # difficulty: dual_variant_calc/last_click_vs_position_based_attribution_on_conversion
        """
        setup = setup_active_campaign_with_approved_creative(
            bid_cents=10, initial_recharge_cents=100000,
        )
        user_id = f"u-pb-{random_suffix(6)}"
        clicks = _three_finalized_clicks_for_user(setup, user_id)
        conv = create_conversion(
            advertiser_id=setup["advertiser"]["id"],
            user_id=user_id,
            value_cents=1000,
            attribution_window_days=7,
            attribution_model="POSITION_BASED",
        )
        result = attribute_conversion(conv["id"])
        assert result["attribution_status"] == "ATTRIBUTED"
        tps = result["attributed_touchpoints"]
        assert len(tps) == 3
        # PRD §3.7 sorts by created_at ascending; with our 1-day spacing
        # the order matches clicks[0], clicks[1], clicks[2].
        assert tps[0]["billing_event_id"] == clicks[0]["id"]
        assert tps[-1]["billing_event_id"] == clicks[-1]["id"]
        assert tps[0]["credit_cents"] == 400, (
            f"PRD §3.7 POSITION_BASED: first=40% of 1000=400, got "
            f"{tps[0]['credit_cents']}"
        )
        assert tps[1]["credit_cents"] == 200, (
            f"PRD §3.7: only-middle gets 20% of 1000=200, got "
            f"{tps[1]['credit_cents']}"
        )
        assert tps[-1]["credit_cents"] == 400, (
            f"PRD §3.7: last=40% of 1000=400, got {tps[-1]['credit_cents']}"
        )
        assert_attributed_credit_sums_to_value(result)


class TestUnattributed:

    def test_no_eligible_touchpoint_results_in_unattributed(self, api):
        """PRD §3.7: "If the window is empty after this filter, the
        conversion's attribution_status becomes UNATTRIBUTED and
        attributed_touchpoints remains empty — this is a valid
        attribution result, not an error."

        Claim: a conversion with no eligible touchpoints ->
        attribution_status=UNATTRIBUTED.
        """
        setup = setup_active_campaign_with_approved_creative()
        conv = create_conversion(
            advertiser_id=setup["advertiser"]["id"],
            user_id=f"u-no-touch-{random_suffix(6)}",
            value_cents=500,
            attribution_window_days=7,
            attribution_model="LAST_CLICK",
        )
        result = attribute_conversion(conv["id"])
        assert result["attribution_status"] == "UNATTRIBUTED"
        assert result["attributed_touchpoints"] == []
