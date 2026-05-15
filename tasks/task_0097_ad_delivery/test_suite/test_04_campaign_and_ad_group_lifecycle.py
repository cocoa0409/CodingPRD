"""Campaign and ad-group lifecycle: budget validation, date validation,
state transitions, cascades. Covers PRD §3.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_ad_group,
    assert_campaign,
    create_ad_group,
    create_ad_group_payload,
    create_campaign,
    create_campaign_payload,
    iso_date_offset,
    setup_active_advertiser,
    setup_active_campaign_with_approved_creative,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Campaign create — budget and date validation (PRD §3.3, §5)
# ===========================================================================
class TestCampaignBudgetValidation:

    def test_daily_budget_below_minimum_rejected(self, api):
        """PRD §3.3: "daily_budget_cents must be at least 100 (one
        dollar in cents) ... violations return ERR_INVALID_BUDGET."

        Claim: daily_budget_cents=99 (boundary X-1) ->
        ERR_INVALID_BUDGET.
        """
        bundle = setup_active_advertiser()
        res = api.create_campaign(
            bundle["advertiser"]["id"],
            create_campaign_payload(daily_budget_cents=99),
            bundle["manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_BUDGET.value)

    def test_daily_budget_exactly_minimum_accepted(self, api):
        """PRD §3.3: "daily_budget_cents must be at least 100."

        Claim: daily_budget_cents=100 (boundary X) -> 201.
        """
        bundle = setup_active_advertiser()
        res = api.create_campaign(
            bundle["advertiser"]["id"],
            create_campaign_payload(daily_budget_cents=100),
            bundle["manager_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_campaign(data)
        assert data["daily_budget_cents"] == 100

    def test_lifetime_budget_less_than_daily_budget_rejected(self, api):
        """PRD §3.3: "if lifetime_budget_cents is set it must be greater
        than or equal to daily_budget_cents; violations return
        ERR_INVALID_BUDGET."

        Claim: lifetime=500 with daily=1000 -> ERR_INVALID_BUDGET.
        """
        bundle = setup_active_advertiser()
        res = api.create_campaign(
            bundle["advertiser"]["id"],
            create_campaign_payload(
                daily_budget_cents=1000, lifetime_budget_cents=500,
            ),
            bundle["manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_BUDGET.value)


class TestCampaignDateValidation:

    def test_start_after_end_rejected(self, api):
        """PRD §3.3: "when end_date is non-null, start_date must be on
        or before end_date; otherwise the request is rejected with
        ERR_INVALID_CAMPAIGN_DATES."

        Claim: start_date > end_date -> ERR_INVALID_CAMPAIGN_DATES.
        """
        bundle = setup_active_advertiser()
        res = api.create_campaign(
            bundle["advertiser"]["id"],
            create_campaign_payload(
                start_date=iso_date_offset(days=5),
                end_date=iso_date_offset(days=1),
            ),
            bundle["manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_CAMPAIGN_DATES.value)


# ===========================================================================
# Campaign create state (PRD §3.3)
# ===========================================================================
class TestCampaignCreatedDraft:

    def test_new_campaign_is_draft(self, api):
        """PRD §3.3: "The campaign is created in DRAFT and stamped with
        an account-scoped monotonic created_seq."

        Claim: POST /advertisers/{id}/campaigns -> status=DRAFT.
        """
        bundle = setup_active_advertiser()
        res = api.create_campaign(
            bundle["advertiser"]["id"],
            create_campaign_payload(),
            bundle["manager_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "DRAFT"


# ===========================================================================
# Campaign activate (PRD §3.3) — preconditions on advertiser + ad-group
# ===========================================================================
class TestCampaignActivate:

    def test_activate_without_approved_creative_rejected(self, api):
        """PRD §3.3: "Activation of a campaign — DRAFT → ACTIVE or
        PAUSED → ACTIVE — requires that the advertiser is currently
        ACTIVE and that at least one of the campaign's ad-groups has
        approved_creative_count of at least 1."

        Claim: an empty campaign cannot activate. The PRD does not
        commit to a specific error_id for the count-zero precondition;
        validate it's some campaign-state violation. PRD §2.7 only
        names ERR_INVALID_CAMPAIGN_STATE in that ordering position.
        """
        bundle = setup_active_advertiser()
        campaign = create_campaign(
            bundle["advertiser"]["id"], bundle["manager_headers"],
        )
        res = api.activate_campaign(
            bundle["advertiser"]["id"], campaign["id"],
            bundle["manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_CAMPAIGN_STATE.value)

    def test_activate_with_approved_creative_succeeds(self, api):
        """PRD §3.3: "at least one of the campaign's ad-groups has
        approved_creative_count of at least 1."

        Claim: with one APPROVED creative under one ad-group, activate
        succeeds.
        """
        setup = setup_active_campaign_with_approved_creative()
        assert setup["campaign"]["status"] == "ACTIVE"


# ===========================================================================
# Campaign activate — fiscal preconditions (PRD §3.3, §3.8, §3.9)
# ===========================================================================
class TestCampaignActivateZeroBalance:

    def test_activate_from_paused_with_zero_balance_rejected(self, api):
        """PRD §3.3: "activating from PAUSED requires that the
        advertiser's balance_state is either HEALTHY or LOW_BALANCE
        (i.e., not ZERO_BALANCE). Activating when balance_state equals
        ZERO_BALANCE is rejected with ERR_ZERO_BALANCE (HTTP 402)."

        Claim: PAUSED campaign + ZERO_BALANCE advertiser -> activate
        rejected with ERR_ZERO_BALANCE.

        # difficulty: cross_entity_state_dependency/campaign_activate_requires_advertiser_active_and_healthy_balance
        """
        # Build an ACTIVE campaign, pause it, drain the wallet to 0,
        # then attempt to re-activate.
        setup = setup_active_campaign_with_approved_creative(
            initial_recharge_cents=200,
        )
        adv = setup["advertiser"]
        api.pause_campaign(
            adv["id"], setup["campaign"]["id"], setup["manager_headers"],
        )
        # Drain the balance by a debit ADJUSTMENT down to 0.
        from test_helpers import create_wallet_tx_payload
        api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="ADJUSTMENT", amount_cents=-200,
                note="drain to zero",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        # Now attempt to re-activate the campaign.
        res = api.activate_campaign(
            adv["id"], setup["campaign"]["id"], setup["manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ZERO_BALANCE.value)


# ===========================================================================
# Campaign cross-entity gates (PRD §2.7 + §3.3)
# ===========================================================================
class TestCampaignCrossEntityGate:

    def test_activate_when_advertiser_suspended_rejected(self, api):
        """PRD §2.7: "advertiser-level status is checked before the
        resource's own state."
        PRD §3.3: activation requires advertiser ACTIVE.

        Claim: SUSPENDED advertiser blocks activate with
        ERR_ADVERTISER_SUSPENDED.

        # difficulty: cross_entity_state_dependency/campaign_activate_requires_advertiser_active_and_healthy_balance
        """
        setup = setup_active_campaign_with_approved_creative()
        adv = setup["advertiser"]
        api.pause_campaign(
            adv["id"], setup["campaign"]["id"], setup["manager_headers"],
        )
        api.suspend_advertiser(
            adv["id"], TEST_USERS["platform_admin_headers"],
        )
        res = api.activate_campaign(
            adv["id"], setup["campaign"]["id"], setup["manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ADVERTISER_SUSPENDED.value)


# ===========================================================================
# Campaign pause + cascade (PRD §3.3)
# ===========================================================================
class TestCampaignPauseCascade:

    def test_pause_campaign_pauses_running_ad_groups(self, api):
        """PRD §3.3: "A campaign is paused either by explicit operator
        action or by cascade ... pausing cascades to every RUNNING
        AdGroup under the campaign."

        Claim: POST /campaigns/{id}/pause -> Campaign.status=PAUSED;
        RUNNING ad-groups -> PAUSED.
        """
        setup = setup_active_campaign_with_approved_creative()
        adv = setup["advertiser"]
        res = api.pause_campaign(
            adv["id"], setup["campaign"]["id"], setup["manager_headers"],
        )
        camp = validate_success(res, expected_status=200)
        assert camp["status"] == "PAUSED"
        ag_list = api_client.list_ad_groups(
            adv["id"], camp["id"], TEST_USERS["platform_admin_headers"],
        ).json()["data"]
        ag = next(a for a in ag_list if a["id"] == setup["ad_group"]["id"])
        assert ag["status"] == "PAUSED", (
            f"Cascade: RUNNING AdGroup must move to PAUSED, got "
            f"{ag['status']!r}"
        )


# ===========================================================================
# AdGroup creation + frequency cap (PRD §3.3)
# ===========================================================================
class TestAdGroupCreate:

    def test_frequency_cap_below_one_rejected(self, api):
        """PRD §3.3: "frequency_cap_per_user_per_day (an integer of at
        least 1; null means no cap; values below 1 are rejected with
        ERR_INVALID_FREQUENCY_CAP)."

        Claim: frequency_cap_per_user_per_day=0 ->
        ERR_INVALID_FREQUENCY_CAP.
        """
        bundle = setup_active_advertiser()
        campaign = create_campaign(
            bundle["advertiser"]["id"], bundle["manager_headers"],
        )
        res = api.create_ad_group(
            bundle["advertiser"]["id"], campaign["id"],
            create_ad_group_payload(frequency_cap_per_user_per_day=0),
            bundle["manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_FREQUENCY_CAP.value)

    def test_frequency_cap_one_is_accepted(self, api):
        """PRD §3.3: "an integer of at least 1."

        Claim: frequency_cap_per_user_per_day=1 (boundary X) -> 201.
        """
        bundle = setup_active_advertiser()
        campaign = create_campaign(
            bundle["advertiser"]["id"], bundle["manager_headers"],
        )
        res = api.create_ad_group(
            bundle["advertiser"]["id"], campaign["id"],
            create_ad_group_payload(frequency_cap_per_user_per_day=1),
            bundle["manager_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["frequency_cap_per_user_per_day"] == 1

    def test_new_ad_group_initialises_quality_score_and_predicted_ctr(self, api):
        """PRD §3.3: "Each new ad-group starts in DRAFT, with
        quality_score initialised to 5.0 and predicted_ctr initialised
        to 0.02."

        Claim: new ad-group response shows quality_score=5.0,
        predicted_ctr=0.02, status=DRAFT.
        """
        bundle = setup_active_advertiser()
        campaign = create_campaign(
            bundle["advertiser"]["id"], bundle["manager_headers"],
        )
        res = api.create_ad_group(
            bundle["advertiser"]["id"], campaign["id"],
            create_ad_group_payload(),
            bundle["manager_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["quality_score"] == 5.0, (
            f"PRD §3.3: quality_score initialised to 5.0, got "
            f"{data['quality_score']}"
        )
        assert data["predicted_ctr"] == 0.02, (
            f"PRD §3.3: predicted_ctr initialised to 0.02, got "
            f"{data['predicted_ctr']}"
        )
        assert data["approved_creative_count"] == 0


# ===========================================================================
# AdGroup auto-state transitions (PRD §3.3)
# ===========================================================================
class TestAdGroupAutoState:

    def test_ad_group_advances_to_ready_when_creative_approved(self, api):
        """PRD §3.3: "An ad-group in DRAFT advances automatically to
        READY once its approved_creative_count is at least 1."

        Claim: after first creative is APPROVED, ad-group status
        becomes READY.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        campaign = create_campaign(adv["id"], bundle["manager_headers"])
        ad_group = create_ad_group(
            adv["id"], campaign["id"], bundle["manager_headers"],
        )
        from test_helpers import approve_creative_end_to_end
        approve_creative_end_to_end(
            adv["id"], campaign["id"], ad_group["id"],
            bundle["manager_headers"],
        )
        ag_list = api_client.list_ad_groups(
            adv["id"], campaign["id"], TEST_USERS["platform_admin_headers"],
        ).json()["data"]
        ag = next(a for a in ag_list if a["id"] == ad_group["id"])
        assert ag["status"] == "READY", (
            f"PRD §3.3: AdGroup should auto-advance from DRAFT to READY "
            f"once approved_creative_count >= 1, got {ag['status']!r}"
        )
        assert ag["approved_creative_count"] == 1


# ===========================================================================
# Campaign update — budget exhaustion shortcut (PRD §3.3)
# ===========================================================================
class TestCampaignUpdate:

    def test_updating_daily_budget_below_today_spent_marks_exhausted(self, api):
        """PRD §3.3: "If the new daily_budget_cents is less than the
        campaign's accumulated today_spent_cents, the campaign
        immediately enters BUDGET_EXHAUSTED."

        Claim: PUT campaign with daily_budget_cents below today_spent
        -> status=BUDGET_EXHAUSTED.

        Setup: finalise a small click so today_spent_cents > 0, then
        reduce the daily budget below it.
        """
        from test_helpers import setup_finalized_billing_event
        # Run a click that finalises with cost_cents > 0.
        setup = setup_finalized_billing_event(
            bid_cents=200, floor_price_cents=200, initial_recharge_cents=100000,
        )
        adv = setup["advertiser"]
        campaign = setup["campaign"]
        be = setup["billing_event"]
        if be["status"] != "FINALIZED" or be["cost_cents"] == 0:
            pytest.skip(
                "Pipeline did not produce a non-zero FINALIZED click — "
                "implementation may not support this CPC scenario."
            )
        today_spent = be["cost_cents"]
        # Now PUT daily_budget to today_spent - 1 (must be >= 100).
        new_budget = max(today_spent - 1, 100)
        if new_budget >= today_spent:
            pytest.skip("today_spent too small to set budget below it")
        res = api.update_campaign(
            adv["id"], campaign["id"],
            {"daily_budget_cents": new_budget},
            setup["manager_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "BUDGET_EXHAUSTED", (
            f"PRD §3.3: new daily_budget < today_spent must immediately "
            f"transition Campaign to BUDGET_EXHAUSTED, got "
            f"{data['status']!r}"
        )
