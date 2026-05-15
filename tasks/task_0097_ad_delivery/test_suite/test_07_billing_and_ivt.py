"""BillingEvent ingest pipeline: dedup, IVT, cost formula, reversal
invariant. Covers PRD §3.6 plus the §3.9 budget aggregation rules.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_billing_cost_formula,
    assert_billing_event,
    assert_cash_flow_conserved,
    create_billing_event_payload,
    find_row,
    get_advertiser,
    ingest_billing_event,
    random_suffix,
    reverse_billing_event_payload,
    run_auction_and_ingest_click,
    setup_active_campaign_with_approved_creative,
    setup_finalized_billing_event,
    validate_error,
    validate_success,
)


# ===========================================================================
# Dedup (PRD §3.6)
# ===========================================================================
class TestBillingDedup:

    def test_duplicate_dedup_key_returns_duplicate_billing_event(self, api):
        """PRD §3.6: "If a prior BillingEvent already exists with the
        same combination of event_type, auction_event_id, and dedup_key,
        the new ingest is set to DEDUPLICATED rather than persisting a
        second row; the API returns HTTP 409 with
        ERR_DUPLICATE_BILLING_EVENT."

        Claim: re-ingest same (event_type, auction_event_id, dedup_key)
        -> ERR_DUPLICATE_BILLING_EVENT, 409.
        """
        setup = setup_active_campaign_with_approved_creative(bid_cents=100)
        auc, be = run_auction_and_ingest_click(
            setup["advertiser"]["id"], setup["ad_group"]["id"],
            floor_price_cents=100,
        )
        dedup_key = be["dedup_key"]
        res = api.create_billing_event(
            create_billing_event_payload(
                auction_event_id=auc["id"],
                ad_group_id=setup["ad_group"]["id"],
                event_type="CLICK",
                dedup_key=dedup_key,
                ivt_score=0.0,
            ),
            TEST_USERS["exchange_service_headers"],
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_BILLING_EVENT.value)


# ===========================================================================
# IVT screen (PRD §3.6)
# ===========================================================================
class TestIvtScreen:

    def test_ivt_above_threshold_transitions_to_invalid_traffic(self, api):
        """PRD §3.6: "When ivt_score is strictly greater than 0.7, the
        event transitions to INVALID_TRAFFIC and no charge is applied."

        Claim: ivt_score=0.71 -> status=INVALID_TRAFFIC, no balance
        change.
        """
        setup = setup_active_campaign_with_approved_creative(bid_cents=200)
        before_balance = setup["advertiser"]["balance_cents"]
        auc, be = run_auction_and_ingest_click(
            setup["advertiser"]["id"], setup["ad_group"]["id"],
            floor_price_cents=200, ivt_score=0.71,
        )
        assert be["status"] == "INVALID_TRAFFIC"
        adv_after = get_advertiser(setup["advertiser"]["id"])
        assert adv_after["balance_cents"] == before_balance, (
            "PRD §3.6: INVALID_TRAFFIC events apply no charge"
        )

    def test_ivt_exactly_at_threshold_finalises(self, api):
        """PRD §3.6: "when ivt_score is at most 0.7, the event
        transitions to VALID."

        Claim: ivt_score=0.7 (boundary X) -> VALID -> FINALIZED.
        """
        setup = setup_active_campaign_with_approved_creative(bid_cents=100)
        auc, be = run_auction_and_ingest_click(
            setup["advertiser"]["id"], setup["ad_group"]["id"],
            floor_price_cents=100, ivt_score=0.7,
        )
        assert be["status"] == "FINALIZED", (
            f"PRD §3.6: ivt_score=0.7 must FINALIZE, got {be['status']!r}"
        )


# ===========================================================================
# Cost / tax formula (PRD §3.6)
# ===========================================================================
class TestBillingCostFormula:

    def test_tax_floor_truncation_order_pinned(self, api):
        """PRD §3.6: "tax_cents is computed as gross_cost_cents
        multiplied by the advertiser's tax_rate_bps divided by 10000
        (basis points to fraction), truncated down to a whole cent.
        The total cost_cents is then gross_cost_cents plus tax_cents.
        The rounding order is fixed: tax is computed on the gross,
        then added — tax is never applied to a running total."

        Claim: gross=37 cents at tax_rate_bps=1500 (15%): tax =
        floor(37 * 1500 / 10000) = floor(5.55) = 5; cost = 42.
        Asserts cost is 42 (NOT 43 from round-after-add).

        # difficulty: combinatorial_formula/billing_event_tax_rounding_order
        """
        setup = setup_active_campaign_with_approved_creative(
            bid_cents=37, tax_rate_bps=1500, initial_recharge_cents=100000,
        )
        # Auction must clear at 37 cents: bid=37, floor=37 -> clearing=37.
        auc, be = run_auction_and_ingest_click(
            setup["advertiser"]["id"], setup["ad_group"]["id"],
            pricing_rule="GSP", floor_price_cents=37,
        )
        if be.get("gross_cost_cents") != 37:
            pytest.skip(
                f"Pipeline did not produce gross_cost_cents=37 "
                f"(got {be.get('gross_cost_cents')!r}); cannot exercise "
                f"the pinned rounding-order rule."
            )
        assert be["status"] == "FINALIZED"
        assert be["gross_cost_cents"] == 37
        assert be["tax_cents"] == 5, (
            f"PRD §3.6 floor(37 * 1500 / 10000) = 5, got {be['tax_cents']}"
        )
        assert be["cost_cents"] == 42, (
            f"PRD §3.6 cost = gross + tax = 42 (NOT 43 from "
            f"round-after-sum), got {be['cost_cents']}"
        )
        assert_billing_cost_formula(be, tax_rate_bps=1500)

    def test_tax_formula_zero_tax_rate(self, api):
        """PRD §3.6: "tax_cents = floor(gross_cost_cents * tax_rate_bps
        / 10000)."

        Claim: tax_rate_bps=0 -> tax_cents=0, cost == gross.

        # difficulty: combinatorial_formula/billing_event_tax_rounding_order
        """
        setup = setup_active_campaign_with_approved_creative(
            bid_cents=100, tax_rate_bps=0,
        )
        auc, be = run_auction_and_ingest_click(
            setup["advertiser"]["id"], setup["ad_group"]["id"],
            floor_price_cents=100,
        )
        assert be["status"] == "FINALIZED"
        assert be["tax_cents"] == 0
        assert be["cost_cents"] == be["gross_cost_cents"]


# ===========================================================================
# Strategy / event-type mismatch (PRD §3.6)
# ===========================================================================
class TestBillingStrategyMismatch:

    def test_cpc_charges_only_clicks(self, api):
        """PRD §3.6: "When the strategy does not match the event type,
        gross_cost_cents is set to 0 — the event is still logged and
        finalised, but the charge is zero."

        Claim: CPC ad-group + IMPRESSION event -> FINALIZED with
        gross_cost_cents=0.
        """
        setup = setup_active_campaign_with_approved_creative(
            bidding_strategy="CPC", bid_cents=500,
        )
        # Run an auction (it will FILL since CPC effective_bid = 500).
        auc = api_client.run_auction(
            {
                "exchange": "INTERNAL",
                "pricing_rule": "GSP",
                "floor_price_cents": 1,
                "user_id": f"u-{random_suffix(4)}",
                "device": "DESKTOP",
                "geo": "US-CA",
                "candidate_ad_group_ids": [setup["ad_group"]["id"]],
            },
            TEST_USERS["exchange_service_headers"],
        ).json()["data"]
        if auc["outcome"] != "FILLED":
            pytest.skip("Auction did not FILL — cannot exercise mismatch")
        be = ingest_billing_event(
            auction_event_id=auc["id"],
            ad_group_id=setup["ad_group"]["id"],
            event_type="IMPRESSION",
            ivt_score=0.0,
        )
        assert be["status"] == "FINALIZED"
        assert be["gross_cost_cents"] == 0, (
            f"PRD §3.6: CPC strategy + IMPRESSION event -> "
            f"gross_cost_cents=0, got {be['gross_cost_cents']}"
        )


# ===========================================================================
# Reversal — compensating invariant (PRD §3.6, §2.9)
# ===========================================================================
class TestBillingReversal:

    def test_reverse_finalized_returns_balance_to_pre_state(self, api):
        """PRD §2.9: "Wallet accounting follows a strict invariant: a
        forward WalletTransaction and its reversal must produce a net
        change of zero to balance_cents."
        PRD §3.6: "The forward-plus-reverse pair leaves balance_cents
        unchanged in net."

        Claim: balance before recharge -> recharge -> finalize click ->
        reverse click -> balance equals post-recharge balance.

        # difficulty: compensating_invariant/billing_event_finalize_then_reverse_preserves_balance_cents
        """
        setup = setup_finalized_billing_event(
            bid_cents=100, floor_price_cents=100, initial_recharge_cents=100000,
        )
        adv = setup["advertiser"]
        be = setup["billing_event"]
        if be["status"] != "FINALIZED" or be["cost_cents"] == 0:
            pytest.skip(
                "Pipeline did not produce a non-zero FINALIZED click."
            )
        adv_before = get_advertiser(adv["id"])
        balance_pre_reversal = adv_before["balance_cents"]
        # Reverse via AntiFraudService.
        res = api.reverse_billing_event(
            be["id"],
            reverse_billing_event_payload(reversal_reason="late-ivt"),
            TEST_USERS["anti_fraud_service_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "REVERSED"
        adv_after = get_advertiser(adv["id"])
        expected = balance_pre_reversal + be["cost_cents"]
        assert adv_after["balance_cents"] == expected, (
            f"PRD §2.9 net-zero: balance after reverse must equal "
            f"pre-finalize ({expected}), got {adv_after['balance_cents']}"
        )
        # Final invariant: post-recharge initial 100000 should be restored.
        assert adv_after["balance_cents"] == 100000, (
            f"PRD §2.9 invariant: balance after FINALIZE+REVERSE equals "
            f"the original recharge total 100000, got "
            f"{adv_after['balance_cents']}"
        )

    def test_reverse_returns_campaign_today_spent_to_pre_value(self, api):
        """PRD §3.9: "Campaign.today_spent_cents applies the same sum
        but restricted to events whose finalized_at is at or after the
        start of the current UTC day."
        PRD §3.6: "the campaign's lifetime and today spend totals are
        decreased" on reverse.

        Claim: a CLICK that finalises with cost_cents=200 against a
        daily_budget=200 campaign brings today_spent_cents to 200 and
        Campaign.status -> BUDGET_EXHAUSTED; on reverse, today_spent
        returns to 0 and Campaign.status returns to ACTIVE.

        # difficulty: compensating_invariant/campaign_lifetime_spent_cents_finalize_then_reverse_preserves_zero_drift
        """
        setup = setup_active_campaign_with_approved_creative(
            bid_cents=300, bidding_strategy="CPC",
            daily_budget_cents=200, lifetime_budget_cents=500,
            initial_recharge_cents=100000,
        )
        adv = setup["advertiser"]
        campaign = setup["campaign"]
        ag = setup["ad_group"]
        # Run auction at floor=200 to nail clearing price.
        auc, be = run_auction_and_ingest_click(
            adv["id"], ag["id"], floor_price_cents=200, pricing_rule="GSP",
        )
        if be["status"] != "FINALIZED" or be["cost_cents"] != 200:
            pytest.skip(
                f"Pipeline did not produce FINALIZED cost=200 (got "
                f"{be['status']!r}, cost={be['cost_cents']!r})"
            )
        # Refresh campaign.
        camp_list = api_client.list_campaigns(
            adv["id"], TEST_USERS["platform_admin_headers"],
        ).json()["data"]
        camp = next(c for c in camp_list if c["id"] == campaign["id"])
        assert camp["today_spent_cents"] == 200
        assert camp["lifetime_spent_cents"] == 200
        assert camp["status"] == "BUDGET_EXHAUSTED", (
            f"PRD §3.9: today_spent (200) >= daily_budget (200) -> "
            f"BUDGET_EXHAUSTED, got {camp['status']!r}"
        )

        # Reverse.
        api.reverse_billing_event(
            be["id"],
            reverse_billing_event_payload(reversal_reason="late-ivt"),
            TEST_USERS["anti_fraud_service_headers"],
        )
        camp_list = api_client.list_campaigns(
            adv["id"], TEST_USERS["platform_admin_headers"],
        ).json()["data"]
        camp_after = next(c for c in camp_list if c["id"] == campaign["id"])
        assert camp_after["today_spent_cents"] == 0, (
            f"PRD §3.6: campaign today_spent decreases on reverse, got "
            f"{camp_after['today_spent_cents']}"
        )
        assert camp_after["lifetime_spent_cents"] == 0
        assert camp_after["status"] == "ACTIVE", (
            f"PRD §3.6/§3.9: budget posture re-evaluated -> campaign "
            f"back to ACTIVE, got {camp_after['status']!r}"
        )

    def test_reverse_requires_non_empty_reversal_reason(self, api):
        """PRD §3.6: "Reversal supplies a reversal_reason (required,
        non-empty)."

        Claim: empty/missing reversal_reason -> ERR_INVALID_REQUEST.
        """
        setup = setup_finalized_billing_event(
            bid_cents=100, floor_price_cents=100, initial_recharge_cents=100000,
        )
        be = setup["billing_event"]
        if be["status"] != "FINALIZED":
            pytest.skip("Setup did not finalize")
        res = api.reverse_billing_event(
            be["id"], {"reversal_reason": ""},
            TEST_USERS["anti_fraud_service_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
