"""Optimistic concurrency control on placement creation and campaign versioning.

Covers difficulty rule optimistic_concurrency plus the corner OCC version-increment claim.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_advertiser_headers,
    TEST_USERS,
    setup_monetized_published_episode,
    create_advertiser_and_active_campaign,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ============================================================================
# Difficulty: optimistic_concurrency / placement_create_stale_campaign_version_rejected
# (also owns Corner errors/stale_campaign_version_on_create_excluded — excluded stub)
# ============================================================================
class TestStaleCampaignVersion:
    def test_second_create_with_stale_version_rejected(self, api):
        """PRD §2.8: "If expected_campaign_version does not equal the campaign's current version at
        the moment the create is processed, the request is rejected with ERR_STALE_CAMPAIGN_VERSION
        and HTTP status 412." The first create bumps the version; reusing the pre-bump value fails.

        Design: Difficulty/optimistic_concurrency/placement_create_stale_campaign_version_rejected
        """
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 3, "offered_positions": ["PRE_ROLL", "POST_ROLL"]})
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        adv_headers = make_advertiser_headers(advertiser["id"])
        stale_version = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
        # First create succeeds and advances campaign.version.
        validate_success(api.create_ad_placement(
            {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "PRE_ROLL",
             "ad_duration_ms": 30000, "forecast_impressions": 5,
             "expected_campaign_version": stale_version}, adv_headers), 201)
        # Second create still carries the pre-bump version.
        res = api.create_ad_placement(
            {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "POST_ROLL",
             "ad_duration_ms": 30000, "forecast_impressions": 5,
             "expected_campaign_version": stale_version}, adv_headers)
        validate_error(res, "ERR_STALE_CAMPAIGN_VERSION", expected_status=412)

    def test_stale_create_does_not_reserve_extra_budget(self, api):
        """PRD §2.8: "refusing the create prevents it from over-reserving against the shared pool."
        After the first create reserves 250, a stale-version second create is refused and the
        campaign's reserved_budget_cents stays at the single 250 (no extra reserve was held).

        Design: Difficulty/optimistic_concurrency/placement_create_stale_campaign_version_rejected
        """
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 3, "offered_positions": ["PRE_ROLL", "POST_ROLL"]})
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        adv_headers = make_advertiser_headers(advertiser["id"])
        stale_version = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
        validate_success(api.create_ad_placement(
            {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "PRE_ROLL",
             "ad_duration_ms": 30000, "forecast_impressions": 5,
             "expected_campaign_version": stale_version}, adv_headers), 201)
        res = api.create_ad_placement(
            {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "POST_ROLL",
             "ad_duration_ms": 30000, "forecast_impressions": 5,
             "expected_campaign_version": stale_version}, adv_headers)
        validate_error(res, "ERR_STALE_CAMPAIGN_VERSION", expected_status=412)
        c = validate_success(api.get_ad_campaign(campaign["id"], adv_headers), 200)
        assert c["reserved_budget_cents"] == 250

    def test_fresh_version_create_succeeds_and_reserves_again(self, api):
        """PRD §2.8: "A request to create an AdPlacement must carry expected_campaign_version, the
        value of the funding campaign's version that the client last observed." Re-reading the
        bumped version lets the second create succeed (201) and reserve again — two 250 reserves
        total 500.

        Design: Difficulty/optimistic_concurrency/placement_create_correct_campaign_version_succeeds
        """
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 3, "offered_positions": ["PRE_ROLL", "POST_ROLL"]})
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        adv_headers = make_advertiser_headers(advertiser["id"])
        v1 = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
        validate_success(api.create_ad_placement(
            {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "PRE_ROLL",
             "ad_duration_ms": 30000, "forecast_impressions": 5,
             "expected_campaign_version": v1}, adv_headers), 201)
        v2 = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
        second = validate_success(api.create_ad_placement(
            {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "POST_ROLL",
             "ad_duration_ms": 30000, "forecast_impressions": 5,
             "expected_campaign_version": v2}, adv_headers), 201)
        assert second["status"] == "PROPOSED"
        c = validate_success(api.get_ad_campaign(campaign["id"], adv_headers), 200)
        assert c["reserved_budget_cents"] == 500

    def test_correct_version_second_placement_is_proposed(self, api):
        """PRD §3.5: "A newly created placement is PROPOSED." A second create against the freshly
        re-read campaign version yields a PROPOSED placement.

        Design: Difficulty/optimistic_concurrency/placement_create_correct_campaign_version_succeeds
        """
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 3, "offered_positions": ["PRE_ROLL", "POST_ROLL"]})
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        adv_headers = make_advertiser_headers(advertiser["id"])
        v1 = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
        validate_success(api.create_ad_placement(
            {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "PRE_ROLL",
             "ad_duration_ms": 30000, "forecast_impressions": 5,
             "expected_campaign_version": v1}, adv_headers), 201)
        v2 = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
        second = validate_success(api.create_ad_placement(
            {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "POST_ROLL",
             "ad_duration_ms": 30000, "forecast_impressions": 5,
             "expected_campaign_version": v2}, adv_headers), 201)
        assert second["status"] == "PROPOSED"


# ============================================================================
# Corner: cross_cutting_complexity_layers / campaign_version_increments_on_placement_create
# ============================================================================
def test_campaign_version_increments_on_placement_create(api):
    """PRD §3.5: "the campaign's version is incremented by one — which is precisely what makes a
    later create with a stale expected_campaign_version fail." A campaign created (v1), activated
    (v2 per §2.4 — every mutation increments version), then a successful placement create takes the
    campaign to version 3.

    Design: Corner/cross_cutting_complexity_layers/campaign_version_increments_on_placement_create
    """
    publisher, show, episode = setup_monetized_published_episode(
        episode_overrides={"total_ad_slots": 2, "offered_positions": ["PRE_ROLL"]})
    advertiser, campaign = create_advertiser_and_active_campaign(
        campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
    adv_headers = make_advertiser_headers(advertiser["id"])
    v_before = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
    validate_success(api.create_ad_placement(
        {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "PRE_ROLL",
         "ad_duration_ms": 30000, "forecast_impressions": 5,
         "expected_campaign_version": v_before}, adv_headers), 201)
    c = validate_success(api.get_ad_campaign(campaign["id"], adv_headers), 200)
    assert c["version"] == v_before + 1
    assert c["version"] == 3
