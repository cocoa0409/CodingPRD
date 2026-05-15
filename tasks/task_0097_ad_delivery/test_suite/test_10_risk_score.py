"""Risk score endpoint — chronic (30d) vs acute (24h) modes. Covers PRD
§3.10.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    ingest_billing_event,
    random_suffix,
    run_auction,
    setup_active_campaign_with_approved_creative,
    validate_success,
)


def _ingest_n_clicks(
    setup: dict, n: int, *, ivt_score: float, user_id: str,
) -> int:
    """Run N auctions and ingest CLICKs at the chosen ivt_score; return
    the count actually persisted (some auctions may not fill if the
    advertiser exhausts budget).
    """
    actual = 0
    for _ in range(n):
        auc = run_auction(
            candidate_ad_group_ids=[setup["ad_group"]["id"]],
            pricing_rule="GSP",
            floor_price_cents=1,
            user_id=user_id,
        )
        if auc["outcome"] != "FILLED":
            return actual
        be = ingest_billing_event(
            auction_event_id=auc["id"],
            ad_group_id=setup["ad_group"]["id"],
            event_type="CLICK",
            dedup_key=f"k-{random_suffix(8)}",
            ivt_score=ivt_score,
        )
        if be["status"] in {"VALID", "FINALIZED", "INVALID_TRAFFIC"}:
            actual += 1
    return actual


class TestRiskScore:

    def test_zero_events_returns_zero_score(self, api):
        """PRD §3.10: "The invalid-traffic rate is the count of
        BillingEvent rows for the advertiser whose status is either
        INVALID_TRAFFIC or REVERSED in the window, divided by the
        greater of 1 and the total count of BillingEvent rows for the
        advertiser in the window. The reject rate is the count of
        Creative rows for the advertiser whose review_status is
        REJECTED and were created in the window, divided by the greater
        of 1 and the total count of Creative rows created in the
        window. The raw score is the invalid-traffic rate times 0.6
        plus the reject rate times 0.4; the published risk score is
        that raw score multiplied by 100, rounded half-up to the
        nearest integer, and capped at 100."

        Claim: an advertiser with no events and a single APPROVED
        creative has reject_rate = 0/1 = 0 and invalid_rate=0; raw=0;
        risk_score=0.
        """
        setup = setup_active_campaign_with_approved_creative()
        adv = setup["advertiser"]
        res = api.get_risk_score(
            adv["id"], TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["risk_score"] == 0, (
            f"PRD §3.10: 0/1 invalid + 0/1 reject -> 0, got "
            f"{data['risk_score']!r}"
        )

    def test_risk_score_is_integer_between_zero_and_one_hundred(self, api):
        """PRD §3.10: "the answer is always an integer between 0 and
        100 inclusive."

        Claim: the risk_score is an int in [0, 100].
        """
        setup = setup_active_campaign_with_approved_creative()
        adv = setup["advertiser"]
        res = api.get_risk_score(
            adv["id"], TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert isinstance(data["risk_score"], int)
        assert 0 <= data["risk_score"] <= 100

    def test_chronic_and_acute_differ_when_recent_events_skew(self, api):
        """PRD §3.10: "The same advertiser computed in chronic and in
        acute mode generally returns two different integer scores
        because the windows differ."
        PRD §3.10 acute: "Same formula but window = last 24h; same
        inputs over the same accounts produce different risk_score
        values from chronic."

        Claim: an advertiser whose recent (last 24h) events are all
        INVALID_TRAFFIC, while its older (older-than-24h-but-within-30d)
        events are mostly VALID, has acute risk_score > chronic
        risk_score. Both endpoints return integers and they are NOT
        equal.

        # difficulty: dual_variant_calc/chronic_vs_acute_advertiser_risk_score
        """
        setup = setup_active_campaign_with_approved_creative(
            bid_cents=1, initial_recharge_cents=1_000_000,
        )
        adv = setup["advertiser"]
        # Older events: 5 VALID clicks (low ivt_score) at "now".
        _ingest_n_clicks(
            setup, n=5, ivt_score=0.0,
            user_id=f"u-older-{random_suffix(4)}",
        )
        # Push the clock 2 days forward — these older clicks now fall
        # outside the 24h acute window but stay within the 30d chronic
        # window.
        api.advance_clock(2 * 86400, TEST_USERS["platform_admin_headers"])

        # Recent events: 5 INVALID_TRAFFIC clicks (ivt_score > 0.7) at
        # the new "now", placing them inside the 24h acute window.
        _ingest_n_clicks(
            setup, n=5, ivt_score=0.95,
            user_id=f"u-recent-{random_suffix(4)}",
        )

        chronic = validate_success(
            api.get_risk_score(
                adv["id"], TEST_USERS["platform_admin_headers"],
            ),
            expected_status=200,
        )
        acute = validate_success(
            api.get_risk_score(
                adv["id"], TEST_USERS["platform_admin_headers"],
                params={"mode": "acute"},
            ),
            expected_status=200,
        )
        assert isinstance(chronic["risk_score"], int)
        assert isinstance(acute["risk_score"], int)
        assert chronic["risk_score"] != acute["risk_score"], (
            "PRD §3.10: chronic and acute over divergent windows must "
            f"produce different integer scores; got chronic="
            f"{chronic['risk_score']}, acute={acute['risk_score']}"
        )
        # And acute must be strictly higher (its 24h window is 5/5 IVT
        # while chronic's 30d window is 5 valid + 5 IVT = 5/10).
        assert acute["risk_score"] > chronic["risk_score"], (
            "PRD §3.10: with all recent traffic INVALID, acute "
            "(skewed) > chronic (averaged), got acute="
            f"{acute['risk_score']}, chronic={chronic['risk_score']}"
        )

    def test_chronic_default_mode_when_unspecified(self, api):
        """PRD §3.10: "A risk score endpoint returns a derived
        reputation score for an advertiser, accepting an optional mode
        query parameter (one of chronic or acute; defaulting to
        chronic)."

        Claim: no mode parameter == mode=chronic — both calls return
        identical risk_score.

        # difficulty: dual_variant_calc/chronic_vs_acute_advertiser_risk_score
        """
        setup = setup_active_campaign_with_approved_creative()
        adv = setup["advertiser"]
        res_default = api.get_risk_score(
            adv["id"], TEST_USERS["platform_admin_headers"],
        )
        res_chronic = api.get_risk_score(
            adv["id"], TEST_USERS["platform_admin_headers"],
            params={"mode": "chronic"},
        )
        d = validate_success(res_default, expected_status=200)
        c = validate_success(res_chronic, expected_status=200)
        assert d["risk_score"] == c["risk_score"], (
            f"PRD §3.10: default mode == chronic; got default="
            f"{d['risk_score']}, chronic={c['risk_score']}"
        )
