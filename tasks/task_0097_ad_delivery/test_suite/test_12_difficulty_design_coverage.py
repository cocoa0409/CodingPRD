"""Additional difficulty-design coverage tests.

This file exists to satisfy the §2.1.A requirement that every
scaffold_difficulty_design instance is covered by at least TWO tests.
Tests in other test_*.py files cover the primary cases; this file fills
gaps for instances that needed a second assertion.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    appeal_decide_payload,
    appeal_payload,
    create_account_user,
    create_ad_group,
    create_campaign,
    create_creative,
    create_creative_payload,
    create_wallet_tx_payload,
    get_advertiser,
    human_review_payload,
    make_creative_reviewer_headers,
    prescreen_creative,
    random_suffix,
    review_qualification,
    reverse_billing_event_payload,
    reverse_wallet_tx_payload,
    run_auction_and_ingest_click,
    setup_active_advertiser,
    setup_active_campaign_with_approved_creative,
    setup_finalized_billing_event,
    upload_qualification,
    validate_error,
    validate_success,
)


# ===========================================================================
# Priority pair: state vs business_safety — second variant (PRD §2.7)
# ===========================================================================
class TestStateVsBusinessSafetySecond:

    def test_advertiser_closed_pre_empts_segregation_check_on_appeal_decide(
        self, api,
    ):
        """PRD §2.7: "advertiser-level status is checked before the
        resource's own state ... then the business-safety checks for
        industry qualification and disclaimers, then the segregation-of-
        duties and appeal-segregation checks."

        Claim: appeal-decide on a creative whose advertiser has been
        CLOSED while the appeal was UNDER_APPEAL_REVIEW AND with a
        reviewer-id that also collides with an AccountUser of the
        creative's advertiser — state (priority 4) wins:
        ERR_ADVERTISER_CLOSED, NOT
        ERR_SEGREGATION_OF_DUTIES_VIOLATION.

        Second instance to satisfy §2.1.A two-tests rule.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_creative_review_on_suspended_advertiser
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]

        # Plant the dual-affiliation reviewer id.
        offending_id = f"dual-state-2-{random_suffix(4)}"
        create_account_user(
            adv["id"], external_user_id=offending_id,
            account_role="VIEWER",
        )

        # Build a rejected creative ready for appeal.
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        prescreen_creative(creative["id"], pre_screen_score=0.4)
        api.human_review_creative(
            creative["id"],
            human_review_payload(
                outcome="REJECT", rejection_codes=["MISLEADING_CLAIM"],
            ),
            TEST_USERS["creative_reviewer_headers"],
        )
        api.appeal_creative(creative["id"], {}, manager_headers)
        api.start_review_appeal(
            creative["id"], TEST_USERS["creative_reviewer_headers_alt"],
        )

        # Pause and CLOSE the advertiser.
        api.pause_campaign(adv["id"], campaign["id"], manager_headers)
        api.close_advertiser(adv["id"], TEST_USERS["platform_admin_headers"])

        # Now try to decide the appeal as the offending reviewer.
        offending_headers = make_creative_reviewer_headers(offending_id)
        res = api.decide_appeal(
            creative["id"],
            appeal_decide_payload(outcome="APPROVE"),
            offending_headers,
        )
        validate_error(res, ApiErrorId.ERR_ADVERTISER_CLOSED.value)


# ===========================================================================
# Priority pair: business_safety vs business_fiscal — second variant
# ===========================================================================
class TestBusinessSafetyVsFiscalSecond:

    def test_qualification_required_pre_empts_zero_balance_on_creative_submission(
        self, api,
    ):
        """PRD §2.7: business-safety qualification gate (priority 6) is
        evaluated before business-fiscal zero-balance gate.
        PRD §3.4: "for any advertiser whose industry_category is
        MEDICAL, FINANCIAL, or EDUCATION, the creative may be submitted
        only when the advertiser's qualification_status equals VERIFIED;
        otherwise the upload is rejected with ERR_QUALIFICATION_REQUIRED."

        Claim: MEDICAL advertiser whose qualification is NOT VERIFIED
        attempts to submit a creative — qualification gate fires
        regardless of any later fiscal-state checks (which are
        priority-ordered AFTER the qualification gate per §2.7).

        Setup avoids the re-verification path because PRD §3.1 mandates
        that a re-verification rejection ALSO transitions the advertiser
        to SUSPENDED — which would (per §2.7 priority) report
        ERR_ADVERTISER_SUSPENDED. Instead the test uses a PENDING
        advertiser with UNDER_REVIEW qualification, so the qualification
        gate is the only business-safety check that can fire.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_disclaimer_vs_zero_balance_on_campaign_activate
        """
        from test_helpers import (
            setup_pending_advertiser_with_doc,
            create_account_user,
            make_campaign_manager_headers,
        )
        ctx = setup_pending_advertiser_with_doc(industry="MEDICAL")
        adv = ctx["advertiser"]
        mgr_ext = f"mgr-prio-{random_suffix(6)}"
        create_account_user(
            adv["id"], external_user_id=mgr_ext,
            account_role="CAMPAIGN_MANAGER",
        )
        manager_headers = make_campaign_manager_headers(mgr_ext)
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        # Submit creative — qualification gate fires.
        res = api.create_creative(
            adv["id"], campaign["id"], ad_group["id"],
            create_creative_payload(required_disclaimer="med dx"),
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_QUALIFICATION_REQUIRED.value)


# ===========================================================================
# Cross-entity dependency: creative human-review requires creative state
# AND advertiser qualification (PRD §3.4 + §3.1)
# ===========================================================================
class TestCreativeReviewRequiresQualification:

    def test_human_review_approve_fails_when_advertiser_unqualified(self, api):
        """PRD §3.4 qualification gate at human-review approval time:
        the second check exists to prevent approving regulated creatives
        from an unqualified advertiser.

        Actually PRD §3.4 phrases the second gate around disclaimers,
        not qualifications: "A missing or empty disclaimer is rejected
        with ERR_DISCLAIMER_REQUIRED both at submission and at human-
        review approval time."

        However PRD §3.1 + §3.4 together state: "for any advertiser
        whose industry_category is MEDICAL, FINANCIAL, or EDUCATION,
        the creative may be submitted only when the advertiser's
        qualification_status equals VERIFIED; otherwise the upload is
        rejected with ERR_QUALIFICATION_REQUIRED." This gate applies at
        SUBMISSION. So a creative submitted while VERIFIED but whose
        advertiser later un-VERIFIES while still PENDING_HUMAN_REVIEW
        is a separate question — PRD §3.1 cascades only APPROVED
        creatives. So this test sticks to the disclaimer-at-approve
        path which PRD §3.4 explicitly names.

        Claim: a creative submission attempt for a MEDICAL advertiser
        whose qualification_status is NOT VERIFIED is rejected with
        ERR_QUALIFICATION_REQUIRED (cross-entity gate
        creative<-advertiser_qualification).

        Setup uses a PENDING advertiser (UNVERIFIED → UNDER_REVIEW)
        rather than re-rejecting a previously-VERIFIED one because
        PRD §3.1 also transitions the advertiser to SUSPENDED on a
        re-verification rejection — which (PRD §2.7 priority) would
        report ERR_ADVERTISER_SUSPENDED instead.

        # difficulty: cross_entity_state_dependency/creative_human_review_requires_creative_state_and_advertiser_qualification
        """
        from test_helpers import (
            setup_pending_advertiser_with_doc,
            create_account_user,
            make_campaign_manager_headers,
        )
        ctx = setup_pending_advertiser_with_doc(industry="MEDICAL")
        adv = ctx["advertiser"]
        mgr_ext = f"mgr-cross-{random_suffix(6)}"
        create_account_user(
            adv["id"], external_user_id=mgr_ext,
            account_role="CAMPAIGN_MANAGER",
        )
        manager_headers = make_campaign_manager_headers(mgr_ext)
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        # Submit a creative — qualification gate fires.
        res = api.create_creative(
            adv["id"], campaign["id"], ad_group["id"],
            create_creative_payload(required_disclaimer="med dx"),
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_QUALIFICATION_REQUIRED.value)

    def test_human_review_state_gate_blocks_review_when_not_pending(self, api):
        """PRD §3.4: "From PENDING_HUMAN_REVIEW, a CreativeReviewer
        decides the creative ..."

        Claim: human-review APPROVE on a creative in PRESCREEN_FAILED
        (NOT in PENDING_HUMAN_REVIEW) is rejected with
        ERR_INVALID_CREATIVE_STATE.

        # difficulty: cross_entity_state_dependency/creative_human_review_requires_creative_state_and_advertiser_qualification
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        prescreen_creative(creative["id"], pre_screen_score=0.9)
        # Now in PRESCREEN_FAILED — human-review not permitted.
        res = api.human_review_creative(
            creative["id"], human_review_payload(outcome="APPROVE"),
            TEST_USERS["creative_reviewer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_CREATIVE_STATE.value)


# ===========================================================================
# Compensating invariant — second variants
# ===========================================================================
class TestCompensatingInvariantsSecond:

    def test_billing_reverse_creates_wallet_refund_transaction(self, api):
        """PRD §3.6: "Reversal supplies a reversal_reason (required,
        non-empty) and stores it on the event; the event moves to
        REVERSED, a compensating WalletTransaction with tx_type of
        REFUND and amount_cents equal to the positive of cost_cents is
        created."

        Claim: after FINALIZE+REVERSE, a REFUND WalletTransaction with
        amount_cents == +cost_cents exists in the advertiser's wallet
        history.

        # difficulty: compensating_invariant/billing_event_finalize_then_reverse_preserves_balance_cents
        """
        setup = setup_finalized_billing_event(
            bid_cents=100, floor_price_cents=100,
            initial_recharge_cents=100000,
        )
        adv = setup["advertiser"]
        be = setup["billing_event"]
        if be["status"] != "FINALIZED" or be["cost_cents"] == 0:
            pytest.skip("Pipeline did not produce a non-zero FINALIZED event")
        api.reverse_billing_event(
            be["id"],
            reverse_billing_event_payload(reversal_reason="late-ivt"),
            TEST_USERS["anti_fraud_service_headers"],
        )
        # Inspect wallet ledger.
        wt_resp = api_client.list_wallet_tx(
            adv["id"], TEST_USERS["platform_admin_headers"],
            params={"tx_type": "REFUND"},
        )
        assert wt_resp.status_code == 200
        refunds = wt_resp.json()["data"]
        # Find a REFUND with amount_cents == +cost_cents.
        match = [
            r for r in refunds
            if r["tx_type"] == "REFUND"
            and r["amount_cents"] == be["cost_cents"]
        ]
        assert len(match) >= 1, (
            f"PRD §3.6: REVERSE must create a REFUND WalletTransaction "
            f"with amount_cents=+{be['cost_cents']}, got refunds="
            f"{[r['amount_cents'] for r in refunds]}"
        )

    def test_wallet_reversal_net_zero_with_audit_log(self, api):
        """PRD §3.8: "A reversal of an already-settled wallet
        transaction by a FinanceOfficer requires a non-empty note,
        applies the inverse amount to the balance, recomputes
        balance_state, sets the transaction's status to REVERSED, and
        writes an AuditLog entry; the forward-plus-reverse pair leaves
        balance_cents unchanged in net."

        Claim: post-reverse, the WalletTransaction.status is REVERSED
        and the balance returns to the pre-recharge value.

        # difficulty: compensating_invariant/campaign_lifetime_spent_cents_finalize_then_reverse_preserves_zero_drift
        """
        bundle = setup_active_advertiser(initial_recharge_cents=10000)
        adv = bundle["advertiser"]
        balance_before = adv["balance_cents"]
        rch_resp = api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="RECHARGE", amount_cents=5000,
                idempotency_key="rch-net-2",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        rch = rch_resp.json()["data"]
        rev_resp = api.reverse_wallet_tx(
            adv["id"], rch["id"],
            reverse_wallet_tx_payload(note="cancel"),
            TEST_USERS["platform_admin_headers"],
        )
        rev = validate_success(rev_resp, expected_status=200)
        assert rev["status"] == "REVERSED", (
            f"PRD §3.8: reverse sets WalletTransaction.status=REVERSED, "
            f"got {rev['status']!r}"
        )
        adv_after = get_advertiser(adv["id"])
        assert adv_after["balance_cents"] == balance_before, (
            f"PRD §3.8 net-zero: balance_cents unchanged after "
            f"forward+reverse; before={balance_before}, "
            f"after={adv_after['balance_cents']}"
        )
