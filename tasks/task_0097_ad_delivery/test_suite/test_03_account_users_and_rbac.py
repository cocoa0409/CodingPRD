"""Account users, role identity threading, and segregation of duties.

Covers PRD §2.1 (entity-backed vs opaque roles), §2.7 (priority order),
§3.2 (account-user creation and the segregation bridge), and the
appeal-segregation rule from §3.4.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_creative_end_to_end,
    assert_account_user,
    build_user_headers,
    create_account_user,
    create_account_user_payload,
    create_ad_group,
    create_campaign,
    create_creative,
    human_review_payload,
    make_account_owner_headers,
    make_campaign_manager_headers,
    make_creative_reviewer_headers,
    prescreen_creative,
    reject_creative_end_to_end,
    setup_active_advertiser,
    setup_active_campaign_with_approved_creative,
    setup_rejected_creative,
    validate_error,
    validate_success,
)


# ===========================================================================
# AccountUser creation (PRD §3.2)
# ===========================================================================
class TestAccountUserCreation:

    def test_account_owner_creation_persists_external_user_id_and_role(self, api):
        """PRD §3.2: "an AccountOwner or PlatformAdmin adds individual
        users by recording an external_user_id and an account_role."

        Claim: POST /advertisers/{id}/users returns the AccountUser with
        the supplied external_user_id and account_role.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        res = api.create_account_user(
            adv["id"],
            create_account_user_payload(
                external_user_id="user-x1", account_role="VIEWER",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_account_user(data)
        assert data["external_user_id"] == "user-x1"
        assert data["account_role"] == "VIEWER"
        assert data["status"] == "ACTIVE", (
            "PRD §2.5: AccountUser.status defaults to ACTIVE"
        )


# ===========================================================================
# Ownership scope (PRD §2.1) — entity-backed role identity threading.
# ===========================================================================
class TestEntityBackedRoleScope:

    def test_campaign_manager_cannot_create_campaign_on_unrelated_advertiser(
        self, api,
    ):
        """PRD §2.1: "When X-User-Role is AccountOwner, CampaignManager,
        or FinanceOfficer, X-User-ID is interpreted as the
        external_user_id of an AccountUser row belonging to the
        advertiser scope of the request; ownership checks compare the
        resource's owning advertiser_id to the advertiser referenced by
        that AccountUser."

        Claim: a CampaignManager whose external_user_id is bound to
        advertiser A1 cannot create a campaign under advertiser A2.
        """
        bundle_a = setup_active_advertiser()
        bundle_b = setup_active_advertiser()
        # CampaignManager from A is invoking on B's path.
        res = api.create_campaign(
            bundle_b["advertiser"]["id"],
            {"name": "x", "daily_budget_cents": 100000,
             "pacing_strategy": "STANDARD",
             "start_date": "2026-01-01"},
            bundle_a["manager_headers"],
        )
        # PRD doesn't bind a specific error_id for cross-advertiser
        # mismatch, only the general "ownership check" rule. Two PRD
        # readers could ship ERR_FORBIDDEN_ROLE (the role is correct but
        # not authorised for THIS advertiser) or ERR_ADVERTISER_NOT_FOUND
        # (the advertiser isn't in this user's scope).
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_FORBIDDEN_ROLE.value,
                ApiErrorId.ERR_ADVERTISER_NOT_FOUND.value,
            ],
        )


# ===========================================================================
# Segregation of duties (PRD §2.1, §3.2, §3.4)
# ===========================================================================
class TestSegregationOfDuties:

    def test_reviewer_who_is_account_user_cannot_human_review_approve(self, api):
        """PRD §2.1: "A reviewer's X-User-ID MUST NOT equal any
        external_user_id belonging to an AccountUser of the creative's
        owning advertiser; if it does, the operation is rejected with
        ERR_SEGREGATION_OF_DUTIES_VIOLATION at HTTP 403."

        Claim: create an AccountUser with external_user_id == reviewer
        opaque id, then human-review approve as that same id ->
        ERR_SEGREGATION_OF_DUTIES_VIOLATION.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]

        # Plant the collision: an AccountUser whose external_user_id
        # equals our reviewer opaque id.
        offending_id = "dual-affiliation-actor-1"
        create_account_user(
            adv["id"], external_user_id=offending_id,
            account_role="VIEWER",
        )

        # Create a Creative all the way to PENDING_HUMAN_REVIEW.
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        prescreen_creative(creative["id"], pre_screen_score=0.4)

        # Attempt review under the offending reviewer id.
        offending_reviewer_headers = make_creative_reviewer_headers(offending_id)
        res = api.human_review_creative(
            creative["id"], human_review_payload(outcome="APPROVE"),
            offending_reviewer_headers,
        )
        validate_error(
            res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value,
        )

    def test_reviewer_who_is_account_user_cannot_human_review_reject(self, api):
        """PRD §3.2: "This check applies to human-review approvals,
        human-review rejections, and appeal decisions — both APPROVE
        and REJECT outcomes on either decision endpoint."

        Claim: REJECT outcome by a colliding reviewer also returns
        ERR_SEGREGATION_OF_DUTIES_VIOLATION.
        """
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]

        offending_id = "dual-affiliation-actor-2"
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

        offending_headers = make_creative_reviewer_headers(offending_id)
        res = api.human_review_creative(
            creative["id"],
            human_review_payload(
                outcome="REJECT", rejection_codes=["MISLEADING_CLAIM"],
            ),
            offending_headers,
        )
        validate_error(
            res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value,
        )

    def test_appeal_decider_cannot_be_original_rejection_reviewer(self, api):
        """PRD §2.1: "A reviewer who decides an appeal MUST NOT be the
        same X-User-ID recorded as the original rejection's reviewer;
        if it is, the operation is rejected with ERR_APPEAL_SAME_REVIEWER
        at HTTP 403."

        Claim: the same reviewer that rejected via human-review cannot
        decide the appeal.
        """
        # Set up a creative that has been REJECTED by reviewer_1.
        bundle = setup_active_advertiser()
        adv = bundle["advertiser"]
        manager_headers = bundle["manager_headers"]
        campaign = create_campaign(adv["id"], manager_headers)
        ad_group = create_ad_group(adv["id"], campaign["id"], manager_headers)
        creative = create_creative(
            adv["id"], campaign["id"], ad_group["id"], manager_headers,
        )
        prescreen_creative(creative["id"], pre_screen_score=0.4)
        reviewer1_headers = TEST_USERS["creative_reviewer_headers"]
        api.human_review_creative(
            creative["id"],
            human_review_payload(
                outcome="REJECT", rejection_codes=["TRADEMARK_VIOLATION"],
            ),
            reviewer1_headers,
        )

        # Advertiser-side files appeal; PRD §3.4 says CampaignManager or
        # AccountOwner.
        api.appeal_creative(creative["id"], {}, manager_headers)

        # Reviewer1 (who originally rejected) accepts the appeal. PRD
        # only restricts the DECIDER on appeal/decide (the appeal-same-
        # reviewer rule), so start-review can be done by anyone with the
        # CreativeReviewer role. Use reviewer2 here regardless to avoid
        # an extra collision dimension.
        reviewer2_headers = TEST_USERS["creative_reviewer_headers_alt"]
        api.start_review_appeal(creative["id"], reviewer2_headers)

        # Now reviewer1 attempts to decide the appeal — must fail.
        res = api.decide_appeal(
            creative["id"],
            human_review_payload(outcome="APPROVE"),
            reviewer1_headers,
        )
        validate_error(res, ApiErrorId.ERR_APPEAL_SAME_REVIEWER.value)


# ===========================================================================
# Priority order (PRD §2.7)
# ===========================================================================
class TestValidationPriority:

    def test_advertiser_suspended_pre_empts_invalid_creative_state(self, api):
        """PRD §2.7: "advertiser-level status is checked before the
        resource's own state. A request to pause an AdGroup whose
        parent advertiser is SUSPENDED will report ERR_ADVERTISER_SUSPENDED,
        not ERR_INVALID_AD_GROUP_STATE, regardless of which check the
        implementer happens to evaluate first internally."

        Claim: pause an already-PAUSED AdGroup whose Advertiser is
        SUSPENDED -> ERR_ADVERTISER_SUSPENDED (priority 4) wins over
        ERR_INVALID_AD_GROUP_STATE (priority 5).
        """
        setup = setup_active_campaign_with_approved_creative()
        adv = setup["advertiser"]
        # First pause the ad-group so its state alone would also fail
        # the pause precondition.
        api.pause_ad_group(
            adv["id"], setup["campaign"]["id"], setup["ad_group"]["id"],
            setup["manager_headers"],
        )
        # Then suspend the advertiser. The cascade may or may not
        # touch a PAUSED ad-group, but the advertiser is now SUSPENDED.
        api.suspend_advertiser(
            adv["id"], TEST_USERS["platform_admin_headers"],
        )
        # Now attempt to pause the ad-group again — the advertiser
        # check must pre-empt the ad-group state check.
        res = api.pause_ad_group(
            adv["id"], setup["campaign"]["id"], setup["ad_group"]["id"],
            setup["manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ADVERTISER_SUSPENDED.value)
