"""Creative submission, pre-screen branches, human-review fork, appeal
cycle. Covers PRD §3.4 in full plus the cross-entity creative+industry
gates from §3.4 and the qualification-required gate from PRD §3.1.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    appeal_decide_payload,
    appeal_payload,
    assert_creative,
    assert_review_decision,
    create_ad_group,
    create_campaign,
    create_creative,
    create_creative_payload,
    find_row,
    human_review_payload,
    make_account_owner_headers,
    make_creative_reviewer_headers,
    prescreen_payload,
    random_suffix,
    setup_active_advertiser,
    setup_pending_advertiser_with_doc,
    setup_rejected_creative,
    upload_qualification,
    review_qualification,
    validate_error,
    validate_success,
)


# ===========================================================================
# Creative submission gates (PRD §3.1, §3.4)
# ===========================================================================
class TestCreativeSubmissionGates:

    def test_medical_advertiser_without_verified_qualification_rejected(self, api):
        """PRD §3.4: "for any advertiser whose industry_category is
        MEDICAL, FINANCIAL, or EDUCATION, the creative may be submitted
        only when the advertiser's qualification_status equals VERIFIED;
        otherwise the upload is rejected with ERR_QUALIFICATION_REQUIRED."

        Claim: MEDICAL advertiser whose qualification is still
        UNDER_REVIEW (not VERIFIED) -> ERR_QUALIFICATION_REQUIRED on
        creative submission.

        Setup avoids the re-verification path because PRD §3.1 mandates
        that a re-verification flipping qualification_status to REJECTED
        also moves the advertiser to SUSPENDED, which would (per PRD
        §2.7 priority order) report ERR_ADVERTISER_SUSPENDED instead.
        Instead the fixture sits on a PENDING advertiser whose
        qualification_status is UNDER_REVIEW so only the qualification
        gate can fire.
        """
        from test_helpers import (
            create_account_user, make_campaign_manager_headers,
        )
        ctx = setup_pending_advertiser_with_doc(industry="MEDICAL")
        adv = ctx["advertiser"]
        mgr_ext = f"mgr-pendmed-{random_suffix(6)}"
        create_account_user(
            adv["id"], external_user_id=mgr_ext,
            account_role="CAMPAIGN_MANAGER",
        )
        manager_headers = make_campaign_manager_headers(mgr_ext)
        # Campaign + ad-group are creatable on a PENDING advertiser
        # (PRD §3.3 forbids creation only on SUSPENDED/CLOSED via
        # advertiser-status priority gate).
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        # Submit a creative — qualification gate fires (qual=UNDER_REVIEW).
        res = api.create_creative(
            adv["id"], campaign["id"], ad_group["id"],
            create_creative_payload(
                required_disclaimer="medical disclaimer",
            ),
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_QUALIFICATION_REQUIRED.value)

    def test_regulated_industry_missing_disclaimer_rejected(self, api):
        """PRD §3.4: "The second is the disclaimer gate: when
        industry_category is one of those three regulated categories,
        required_disclaimer must be present and non-empty. A missing or
        empty disclaimer is rejected with ERR_DISCLAIMER_REQUIRED both
        at submission and at human-review approval time."

        Claim: MEDICAL advertiser submits creative without
        required_disclaimer -> ERR_DISCLAIMER_REQUIRED.
        """
        bundle = setup_active_advertiser(industry="MEDICAL")
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        # Omit required_disclaimer (default None).
        res = api.create_creative(
            adv["id"], campaign["id"], ad_group["id"],
            create_creative_payload(),  # no disclaimer
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_DISCLAIMER_REQUIRED.value)

    def test_general_industry_no_disclaimer_required(self, api):
        """PRD §3.4: "when industry_category is one of those three
        regulated categories, required_disclaimer must be present and
        non-empty."

        Claim: GENERAL advertiser may submit a creative without a
        disclaimer.
        """
        bundle = setup_active_advertiser(industry="GENERAL")
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        res = api.create_creative(
            adv["id"], campaign["id"], ad_group["id"],
            create_creative_payload(),  # no disclaimer
            manager_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_creative(data)
        assert data["review_status"] == "PENDING_PRESCREEN", (
            "PRD §3.4: creative enters review in PENDING_PRESCREEN"
        )


# ===========================================================================
# Pre-screen score branches (PRD §3.4)
# ===========================================================================
class TestPrescreenBranches:

    def test_score_at_or_above_0_8_transitions_to_prescreen_failed(self, api):
        """PRD §3.4: "If pre_screen_score is at least 0.8, the creative
        moves to PRESCREEN_FAILED."

        Claim: pre_screen_score=0.8 (boundary X) -> PRESCREEN_FAILED.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        res = api.prescreen_creative(
            creative["id"],
            prescreen_payload(pre_screen_score=0.8),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["review_status"] == "PRESCREEN_FAILED"

    def test_score_below_0_5_transitions_to_human_review(self, api):
        """PRD §3.4: "If pre_screen_score is strictly less than 0.5,
        the creative moves to PENDING_HUMAN_REVIEW."

        Claim: pre_screen_score=0.4 -> PENDING_HUMAN_REVIEW.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        res = api.prescreen_creative(
            creative["id"],
            prescreen_payload(pre_screen_score=0.4),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["review_status"] == "PENDING_HUMAN_REVIEW"

    def test_borderline_score_band_escalates_to_human_review_with_borderline_notes(
        self, api,
    ):
        """PRD §3.4: "If pre_screen_score is in the half-open interval
        starting at 0.5 inclusive and ending at 0.8 exclusive — the
        borderline band — the creative also moves to PENDING_HUMAN_REVIEW,
        but the recorded PRESCREEN decision carries notes set to
        borderline to flag it for the human reviewer."

        Claim: pre_screen_score=0.5 (lower boundary X of borderline) ->
        PENDING_HUMAN_REVIEW, and the ReviewDecision audit log has the
        notes='borderline' flag.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        res = api.prescreen_creative(
            creative["id"],
            prescreen_payload(pre_screen_score=0.5),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["review_status"] == "PENDING_HUMAN_REVIEW"
        # Inspect the review-decision log via the list endpoint.
        rd_resp = api_client.list_review_decisions(
            creative["id"], TEST_USERS["platform_admin_headers"],
        )
        assert rd_resp.status_code == 200
        rds = rd_resp.json()["data"]
        # Find the PRESCREEN entry.
        prescreen = next(r for r in rds if r["decision_type"] == "PRESCREEN")
        assert_review_decision(prescreen)
        assert prescreen.get("notes") == "borderline", (
            f"PRD §3.4 borderline band must set notes='borderline', got "
            f"{prescreen.get('notes')!r}"
        )

    def test_explicit_pass_override_routes_to_human_review(self, api):
        """PRD §3.4: "The pre-screen endpoint also accepts an explicit
        outcome override: an outcome of FAIL forces PRESCREEN_FAILED,
        and an outcome of PASS forces PENDING_HUMAN_REVIEW."

        Claim: outcome=PASS forces PENDING_HUMAN_REVIEW regardless of
        score.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        # Score would otherwise FAIL (>=0.8).
        res = api.prescreen_creative(
            creative["id"],
            prescreen_payload(pre_screen_score=0.9, outcome="PASS"),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["review_status"] == "PENDING_HUMAN_REVIEW"


# ===========================================================================
# Human-review side effects (PRD §3.4)
# ===========================================================================
class TestHumanReviewSideEffects:

    def test_approve_increments_approved_creative_count(self, api):
        """PRD §3.4: "An APPROVE outcome moves the creative to APPROVED,
        increments the parent ad-group's approved_creative_count,
        records a ReviewDecision with decision_type of HUMAN_REVIEW, and
        emits an AuditLog entry with action of REVIEW_DECISION."

        Claim: APPROVE -> Creative.review_status=APPROVED;
        AdGroup.approved_creative_count incremented by 1.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        api.prescreen_creative(
            creative["id"], prescreen_payload(pre_screen_score=0.1),
            TEST_USERS["platform_admin_headers"],
        )
        before_count = ad_group["approved_creative_count"]
        res = api.human_review_creative(
            creative["id"], human_review_payload(outcome="APPROVE"),
            TEST_USERS["creative_reviewer_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["review_status"] == "APPROVED"
        # Refresh ad-group.
        ag_list = api_client.list_ad_groups(
            adv["id"], campaign["id"], TEST_USERS["platform_admin_headers"],
        ).json()["data"]
        ag = next(a for a in ag_list if a["id"] == ad_group["id"])
        assert ag["approved_creative_count"] == before_count + 1

    def test_reject_requires_non_empty_rejection_codes(self, api):
        """PRD §3.4: "A REJECT outcome moves the creative to REJECTED,
        requires that the supplied rejection_codes array is non-empty."

        Claim: REJECT with empty rejection_codes -> error.

        PRD does not commit to a specific error_id for this shape check;
        ERR_INVALID_REQUEST is the natural reading.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        api.prescreen_creative(
            creative["id"], prescreen_payload(pre_screen_score=0.1),
            TEST_USERS["platform_admin_headers"],
        )
        res = api.human_review_creative(
            creative["id"],
            human_review_payload(outcome="REJECT", rejection_codes=[]),
            TEST_USERS["creative_reviewer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_reject_persists_codes_on_creative_and_decision(self, api):
        """PRD §3.4: "persists those codes both onto the creative's own
        rejection_codes field and onto the ReviewDecision."

        Claim: REJECT codes appear on Creative.rejection_codes and on
        the corresponding ReviewDecision.rejection_codes.
        """
        codes = ["MISLEADING_CLAIM", "NO_DISCLAIMER"]
        ctx = setup_rejected_creative()
        # setup_rejected_creative uses ["MISLEADING_CLAIM"]. Use it as-is
        # and check that the codes round-trip.
        creative = ctx["creative"]
        assert creative["review_status"] == "REJECTED"
        assert "MISLEADING_CLAIM" in creative["rejection_codes"], (
            f"rejection_codes must round-trip; got "
            f"{creative['rejection_codes']!r}"
        )
        # Now check ReviewDecision.
        rd_resp = api_client.list_review_decisions(
            creative["id"], TEST_USERS["creative_reviewer_headers"],
        )
        rds = rd_resp.json()["data"]
        hr = next(
            r for r in rds
            if r["decision_type"] == "HUMAN_REVIEW" and r["outcome"] == "REJECT"
        )
        assert "MISLEADING_CLAIM" in hr["rejection_codes"]


# ===========================================================================
# Appeal cycle (PRD §3.4)
# ===========================================================================
class TestAppealCycle:

    def test_appeal_on_rejected_creative_moves_to_appeal_filed(self, api):
        """PRD §3.4: "on success the creative moves to APPEAL_FILED and
        appeal_count is set to 1."

        Claim: POST /creatives/{id}/appeal on REJECTED creative ->
        APPEAL_FILED, appeal_count=1.

        # difficulty: non_linear_state_machine/creative_review_branching_and_cycle_via_appeal
        """
        ctx = setup_rejected_creative()
        creative = ctx["creative"]
        manager_headers = ctx["manager_headers"]
        res = api.appeal_creative(creative["id"], {}, manager_headers)
        data = validate_success(res, expected_status=200)
        assert data["review_status"] == "APPEAL_FILED"
        assert data["appeal_count"] == 1

    def test_second_appeal_rejected_with_appeal_already_filed(self, api):
        """PRD §3.4: "The appeal is rejected with
        ERR_APPEAL_ALREADY_FILED if appeal_count is already 1."

        Claim: second appeal attempt -> ERR_APPEAL_ALREADY_FILED.

        # difficulty: non_linear_state_machine/creative_review_branching_and_cycle_via_appeal
        """
        ctx = setup_rejected_creative()
        creative = ctx["creative"]
        manager_headers = ctx["manager_headers"]
        api.appeal_creative(creative["id"], {}, manager_headers)
        # Walk it through to UNDER_APPEAL_REVIEW -> REJECTED again, so
        # creative is back in REJECTED but appeal_count is still 1.
        api.start_review_appeal(
            creative["id"], TEST_USERS["creative_reviewer_headers_alt"],
        )
        api.decide_appeal(
            creative["id"],
            appeal_decide_payload(
                outcome="REJECT", rejection_codes=["MISLEADING_CLAIM"],
            ),
            TEST_USERS["creative_reviewer_headers_alt"],
        )
        # Second appeal — should fail with ERR_APPEAL_ALREADY_FILED.
        res = api.appeal_creative(creative["id"], {}, manager_headers)
        validate_error(res, ApiErrorId.ERR_APPEAL_ALREADY_FILED.value)

    def test_appeal_full_cycle_branching_back_to_rejected(self, api):
        """PRD §3.4: REJECTED -> APPEAL_FILED -> UNDER_APPEAL_REVIEW ->
        REJECTED is the full appeal cycle ending in REJECTED.

        Claim: walking the entire cycle ends with review_status=REJECTED
        and appeal_count=1.

        # difficulty: non_linear_state_machine/creative_review_branching_and_cycle_via_appeal
        """
        ctx = setup_rejected_creative()
        creative = ctx["creative"]
        manager_headers = ctx["manager_headers"]
        api.appeal_creative(creative["id"], {}, manager_headers)
        api.start_review_appeal(
            creative["id"], TEST_USERS["creative_reviewer_headers_alt"],
        )
        res = api.decide_appeal(
            creative["id"],
            appeal_decide_payload(
                outcome="REJECT", rejection_codes=["MISLEADING_CLAIM"],
            ),
            TEST_USERS["creative_reviewer_headers_alt"],
        )
        data = validate_success(res, expected_status=200)
        assert data["review_status"] == "REJECTED"
        assert data["appeal_count"] == 1


# ===========================================================================
# Parallel: Advertiser status x balance_state (PRD §2.5, §3.9)
# ===========================================================================
class TestAdvertiserParallelDimensions:

    def test_advertiser_status_and_balance_state_evolve_independently(self, api):
        """PRD §2.5: "It also carries an independent qualification_status
        in UNVERIFIED, UNDER_REVIEW, VERIFIED, or REJECTED, and a
        balance_state in HEALTHY, LOW_BALANCE, or ZERO_BALANCE — the
        latter is a parallel dimension to status and is recomputed on
        every wallet ledger movement."

        Claim: SUSPENDED advertiser can hold HEALTHY balance_state, and
        re-recharging while SUSPENDED moves balance_state independently
        of status. Tagged for difficulty design.

        # difficulty: non_linear_state_machine/advertiser_parallel_status_and_balance_state
        """
        from test_helpers import setup_active_advertiser, get_advertiser
        bundle = setup_active_advertiser(initial_recharge_cents=200000)
        adv = bundle["advertiser"]
        # Initially: ACTIVE + HEALTHY.
        assert adv["status"] == "ACTIVE"
        assert adv["balance_state"] == "HEALTHY"

        # Drain balance to 0 via ADJUSTMENT (debit -200000).
        from test_helpers import create_wallet_tx_payload
        api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="ADJUSTMENT", amount_cents=-200000,
                note="drain to zero",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        refreshed = get_advertiser(adv["id"])
        assert refreshed["balance_state"] == "ZERO_BALANCE", (
            "PRD §3.9: balance_cents=0 -> balance_state=ZERO_BALANCE"
        )
        assert refreshed["status"] == "ACTIVE", (
            "Status dimension untouched by balance ledger movement"
        )

        # Suspend (status dimension) while leaving balance at zero.
        api.suspend_advertiser(
            adv["id"], TEST_USERS["platform_admin_headers"],
        )
        refreshed = get_advertiser(adv["id"])
        assert refreshed["status"] == "SUSPENDED"
        assert refreshed["balance_state"] == "ZERO_BALANCE"

        # Recharge to HEALTHY while still SUSPENDED.
        api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="RECHARGE", amount_cents=50000,
            ),
            TEST_USERS["platform_admin_headers"],
        )
        refreshed = get_advertiser(adv["id"])
        assert refreshed["status"] == "SUSPENDED"
        assert refreshed["balance_state"] == "HEALTHY", (
            "PRD §3.9: balance > threshold -> HEALTHY, regardless of "
            "status dimension"
        )

    def test_advertiser_balance_state_transitions_active_to_zero(self, api):
        """PRD §3.9: balance_state transitions on every wallet movement.

        Claim: from balance_cents=100000 (HEALTHY) decrement past
        low_balance_threshold_cents=10000 to enter LOW_BALANCE, then
        decrement past zero to enter ZERO_BALANCE.

        # difficulty: non_linear_state_machine/advertiser_parallel_status_and_balance_state
        """
        from test_helpers import setup_active_advertiser, get_advertiser
        bundle = setup_active_advertiser(
            initial_recharge_cents=100000,
        )  # threshold default 10000
        adv = bundle["advertiser"]
        assert adv["balance_state"] == "HEALTHY"
        # Debit 90001 -> balance=9999 -> LOW_BALANCE.
        from test_helpers import create_wallet_tx_payload
        api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="ADJUSTMENT", amount_cents=-90001,
                note="enter low balance",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        adv2 = get_advertiser(adv["id"])
        assert adv2["balance_cents"] == 9999
        assert adv2["balance_state"] == "LOW_BALANCE", (
            f"PRD §3.9: 0 < balance <= threshold -> LOW_BALANCE, got "
            f"{adv2['balance_state']!r}"
        )
        # Debit 9999 more -> balance=0 -> ZERO_BALANCE.
        api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="ADJUSTMENT", amount_cents=-9999,
                note="enter zero balance",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        adv3 = get_advertiser(adv["id"])
        assert adv3["balance_cents"] == 0
        assert adv3["balance_state"] == "ZERO_BALANCE"
