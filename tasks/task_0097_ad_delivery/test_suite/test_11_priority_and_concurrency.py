"""Validation priority conflicts and concurrency outcomes.

Covers PRD §2.7 (priority ordering with deterministic winners), §3.4
(parallel reviewer scenarios), and §3.6 (duplicate billing-event race).
Tests that align with difficulty-design rules 5 and 9 / concurrency.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_account_user,
    create_ad_group,
    create_campaign,
    create_billing_event_payload,
    create_creative,
    create_creative_payload,
    create_wallet_tx_payload,
    human_review_payload,
    make_creative_reviewer_headers,
    prescreen_creative,
    random_suffix,
    run_auction_and_ingest_click,
    run_race,
    setup_active_advertiser,
    setup_active_campaign_with_approved_creative,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Priority conflict — state vs business_safety (PRD §2.7)
# ===========================================================================
class TestPriorityConflicts:

    def test_suspended_advertiser_pre_empts_segregation_of_duties_check(self, api):
        """PRD §2.7: "advertiser-level status is checked before the
        resource's own state, then the business-safety checks for
        industry qualification and disclaimers, then the segregation-
        of-duties and appeal-segregation checks."

        Claim: human-review on a creative whose advertiser is SUSPENDED
        AND the reviewer is also a dual-affiliated AccountUser ->
        advertiser-status check (priority 4) wins:
        ERR_ADVERTISER_SUSPENDED (NOT ERR_SEGREGATION_OF_DUTIES_VIOLATION).

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_creative_review_on_suspended_advertiser
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]

        # Plant the dual-affiliation reviewer id.
        offending_id = "dual-prio-1"
        create_account_user(
            adv["id"], external_user_id=offending_id,
            account_role="VIEWER",
        )

        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        prescreen_creative(creative["id"], pre_screen_score=0.4)

        # Now suspend the advertiser.
        api.suspend_advertiser(
            adv["id"], TEST_USERS["platform_admin_headers"],
        )

        # Attempt human-review approval with the offending reviewer.
        # State (advertiser SUSPENDED, priority 4) must win over
        # business_safety (segregation, priority 8).
        offending_headers = make_creative_reviewer_headers(offending_id)
        res = api.human_review_creative(
            creative["id"],
            human_review_payload(outcome="APPROVE"),
            offending_headers,
        )
        validate_error(res, ApiErrorId.ERR_ADVERTISER_SUSPENDED.value)

    def test_disclaimer_pre_empts_qualification_for_submission(self, api):
        """PRD §2.7 priority ordering: qualification (priority 6) is
        evaluated before disclaimer (priority 7).

        Claim: MEDICAL advertiser with qualification UNVERIFIED + no
        disclaimer -> qualification check (priority 6) wins:
        ERR_QUALIFICATION_REQUIRED, NOT ERR_DISCLAIMER_REQUIRED.

        Setup avoids the re-verification path because PRD §3.1 dictates
        that a re-verification rejection ALSO transitions the advertiser
        to SUSPENDED, which (PRD §2.7 priority) would report
        ERR_ADVERTISER_SUSPENDED. The fixture instead uses a PENDING
        advertiser whose qualification_status is UNDER_REVIEW so only
        the qualification gate vs disclaimer gate can fire.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_disclaimer_vs_zero_balance_on_campaign_activate
        """
        from test_helpers import (
            setup_pending_advertiser_with_doc,
            create_account_user,
            make_campaign_manager_headers,
            random_suffix,
        )
        ctx = setup_pending_advertiser_with_doc(industry="MEDICAL")
        adv = ctx["advertiser"]
        mgr_ext = f"mgr-pri-{random_suffix(6)}"
        create_account_user(
            adv["id"], external_user_id=mgr_ext,
            account_role="CAMPAIGN_MANAGER",
        )
        manager_headers = make_campaign_manager_headers(mgr_ext)
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        # No disclaimer + UNDER_REVIEW qualification — qualification
        # gate fires first.
        res = api.create_creative(
            adv["id"], campaign["id"], ad_group["id"],
            create_creative_payload(),  # no disclaimer
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_QUALIFICATION_REQUIRED.value)


# ===========================================================================
# Concurrency — review serialisation (PRD §3.4)
# ===========================================================================
class TestReviewSerialisation:

    def test_concurrent_human_review_approve_and_archive_serialise(self, api):
        """PRD §3.4: "When an approval and an archival happen
        simultaneously on a creative in PENDING_HUMAN_REVIEW, exactly
        one wins and the loser receives ERR_INVALID_CREATIVE_STATE."

        Claim: race(approve, archive) results in exactly one success
        and one ERR_INVALID_CREATIVE_STATE failure.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        prescreen_creative(creative["id"], pre_screen_score=0.4)

        results = run_race(
            lambda: api.human_review_creative(
                creative["id"], human_review_payload(outcome="APPROVE"),
                TEST_USERS["creative_reviewer_headers"],
            ),
            lambda: api.archive_creative(creative["id"], manager_headers),
        )
        outcome = assert_exactly_one_succeeds(*results)
        # The loser must specifically return ERR_INVALID_CREATIVE_STATE
        # per PRD §3.4.
        loser = outcome["failures"][0]
        loser_body = loser.json()
        assert loser_body["data"]["error_id"] == \
            ApiErrorId.ERR_INVALID_CREATIVE_STATE.value, (
                f"PRD §3.4: loser must receive ERR_INVALID_CREATIVE_STATE, "
                f"got {loser_body['data']['error_id']!r}"
            )

    def test_concurrent_dual_reviewers_review_already_decided(self, api):
        """PRD §3.4: "Two reviewers attempting to decide the same
        creative in PENDING_HUMAN_REVIEW simultaneously must serialise:
        at most one approval is persisted, and the loser receives
        ERR_REVIEW_ALREADY_DECIDED (HTTP 409)."

        Claim: race(reviewer-A approve, reviewer-B approve) -> exactly
        one succeeds; loser receives ERR_REVIEW_ALREADY_DECIDED.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        prescreen_creative(creative["id"], pre_screen_score=0.4)

        results = run_race(
            lambda: api.human_review_creative(
                creative["id"], human_review_payload(outcome="APPROVE"),
                TEST_USERS["creative_reviewer_headers"],
            ),
            lambda: api.human_review_creative(
                creative["id"], human_review_payload(outcome="APPROVE"),
                TEST_USERS["creative_reviewer_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == \
            ApiErrorId.ERR_REVIEW_ALREADY_DECIDED.value, (
                f"PRD §3.4: loser must receive "
                f"ERR_REVIEW_ALREADY_DECIDED, got "
                f"{loser_body['data']['error_id']!r}"
            )


# ===========================================================================
# Concurrency — billing dedup race (PRD §3.6)
# ===========================================================================
class TestBillingDedupRace:

    def test_concurrent_duplicate_ingests_yield_one_persisted_one_dedup_error(
        self, api,
    ):
        """PRD §3.6: "Two simultaneous ingests with identical
        (event_type, auction_event_id, dedup_key) serialise — exactly
        one row is persisted and the loser receives
        ERR_DUPLICATE_BILLING_EVENT (HTTP 409). The unique constraint
        is on that triple; first-writer-wins."

        Claim: race(two CLICK ingests with the same triple) -> exactly
        one 2xx, one ERR_DUPLICATE_BILLING_EVENT.
        """
        setup = setup_active_campaign_with_approved_creative(bid_cents=100)
        adv = setup["advertiser"]
        # Run an auction first.
        from test_helpers import run_auction
        auc = run_auction(
            candidate_ad_group_ids=[setup["ad_group"]["id"]],
            pricing_rule="GSP",
            floor_price_cents=100,
        )
        dedup_key = f"race-{random_suffix(8)}"

        def ingest():
            return api.create_billing_event(
                create_billing_event_payload(
                    auction_event_id=auc["id"],
                    ad_group_id=setup["ad_group"]["id"],
                    event_type="CLICK",
                    dedup_key=dedup_key,
                    ivt_score=0.0,
                ),
                TEST_USERS["exchange_service_headers"],
            )

        results = run_race(ingest, ingest)
        outcome = assert_exactly_one_succeeds(*results)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == \
            ApiErrorId.ERR_DUPLICATE_BILLING_EVENT.value, (
                f"PRD §3.6: loser must receive "
                f"ERR_DUPLICATE_BILLING_EVENT, got "
                f"{loser_body['data']['error_id']!r}"
            )


# ===========================================================================
# Idempotency conflict race (PRD §3.8)
# ===========================================================================
class TestIdempotencyConflictRace:

    def test_concurrent_recharges_same_idempotency_key(self, api):
        """PRD §3.8: "the balance is only credited once."

        Claim: race(two RECHARGEs with same idempotency_key) -> exactly
        one 2xx, one ERR_IDEMPOTENCY_CONFLICT; balance reflects single
        credit.
        """
        bundle = setup_active_advertiser(initial_recharge_cents=1000)
        adv = bundle["advertiser"]
        key = f"race-idem-{random_suffix(6)}"

        def recharge():
            return api.create_wallet_tx(
                adv["id"],
                create_wallet_tx_payload(
                    tx_type="RECHARGE", amount_cents=500,
                    idempotency_key=key,
                ),
                TEST_USERS["platform_admin_headers"],
            )

        results = run_race(recharge, recharge)
        outcome = assert_exactly_one_succeeds(*results)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == \
            ApiErrorId.ERR_IDEMPOTENCY_CONFLICT.value, (
                f"PRD §3.8: loser must receive ERR_IDEMPOTENCY_CONFLICT, "
                f"got {loser_body['data']['error_id']!r}"
            )
        # Balance should reflect ONE credit, not two.
        from test_helpers import get_advertiser
        refreshed = get_advertiser(adv["id"])
        assert refreshed["balance_cents"] == 1500
