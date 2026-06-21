"""Cascades, conservation invariants, and numeric boundary precision.

Covers difficulty rules transitive_cascade, compensating_invariant, and
boundary_precision_check.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    make_publisher_headers,
    make_advertiser_headers,
    TEST_USERS,
    create_publisher,
    create_active_show,
    create_published_ready_episode,
    create_advertiser_and_active_campaign,
    create_inserted_placement,
    create_proposed_placement,
    current_campaign_version,
    setup_monetized_published_episode,
    api_client,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ============================================================================
# Difficulty: transitive_cascade / show_suspend_cascade_depth3_to_campaign_budget
# ============================================================================
class TestShowSuspendCascade:
    def _setup_suspendable(self):
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 1, "offered_positions": ["PRE_ROLL"]})
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 100000, "bid_cpm_cents": 50000})
        placement = create_inserted_placement(advertiser, campaign, episode, forecast_impressions=5)
        return publisher, show, episode, advertiser, campaign, placement

    def test_suspend_unpublishes_episode_and_cancels_placement(self, api):
        """PRD §3.1: "First, each episode of the show whose publish_status is PUBLISHED is moved to
        UNPUBLISHED. Second, on each of those episodes, every ad placement in PROPOSED or INSERTED
        is moved to CANCELLED."

        Design: Difficulty/transitive_cascade/show_suspend_cascade_depth3_to_campaign_budget
        """
        publisher, show, episode, advertiser, campaign, placement = self._setup_suspendable()
        suspended = validate_success(api.suspend_show(show["id"], ADMIN), 200)
        assert suspended["status"] == "SUSPENDED"
        pub_headers = make_publisher_headers(publisher["id"])
        ep = validate_success(api.get_episode(episode["id"], pub_headers), 200)
        assert ep["publish_status"] == "UNPUBLISHED"
        adv_headers = make_advertiser_headers(advertiser["id"])
        pl = validate_success(api.get_ad_placement(placement["id"], adv_headers), 200)
        assert pl["status"] == "CANCELLED"

    def test_suspend_releases_campaign_reserve_to_full_budget(self, api):
        """PRD §3.1: "Third, each cancelled placement releases its estimated_cost_cents back to the
        funding campaign, whose reserved_budget_cents and available_budget_cents are recomputed".
        Reserve 250 released => reserved 0, available back to the full 100000.

        Design: Difficulty/transitive_cascade/show_suspend_cascade_depth3_to_campaign_budget
        """
        publisher, show, episode, advertiser, campaign, placement = self._setup_suspendable()
        api.suspend_show(show["id"], ADMIN)
        adv_headers = make_advertiser_headers(advertiser["id"])
        c = validate_success(api.get_ad_campaign(campaign["id"], adv_headers), 200)
        assert c["reserved_budget_cents"] == 0
        assert c["available_budget_cents"] == 100000


# ============================================================================
# Difficulty: transitive_cascade / campaign_pause_cascade_depth2_rejects_proposed
# ============================================================================
class TestCampaignPauseCascade:
    def _setup_paused_with_mixed_placements(self):
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 3, "offered_positions": ["PRE_ROLL", "POST_ROLL", "MID_ROLL"]})
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        inserted = create_inserted_placement(advertiser, campaign, episode,
                                             position="PRE_ROLL", forecast_impressions=5)
        proposed = create_proposed_placement(advertiser, campaign, episode,
                                             position="POST_ROLL", forecast_impressions=5)
        return publisher, show, episode, advertiser, campaign, inserted, proposed

    def test_pause_rejects_proposed_leaves_inserted(self, api):
        """PRD §3.4: "pausing rejects every placement of the campaign that is still PROPOSED
        (moving each PROPOSED -> REJECTED and releasing its reserve ...) while leaving INSERTED
        placements intact."

        Design: Difficulty/transitive_cascade/campaign_pause_cascade_depth2_rejects_proposed
        """
        publisher, show, episode, advertiser, campaign, inserted, proposed = \
            self._setup_paused_with_mixed_placements()
        adv_headers = make_advertiser_headers(advertiser["id"])
        paused = validate_success(api.pause_ad_campaign(campaign["id"], adv_headers), 200)
        assert paused["status"] == "PAUSED"
        prop = validate_success(api.get_ad_placement(proposed["id"], adv_headers), 200)
        assert prop["status"] == "REJECTED"
        ins = validate_success(api.get_ad_placement(inserted["id"], adv_headers), 200)
        assert ins["status"] == "INSERTED"

    def test_pause_releases_only_proposed_reserve(self, api):
        """PRD §3.4: "moving each PROPOSED -> REJECTED and releasing its reserve, with
        reserved_budget_cents recomputed". After pause, only the INSERTED placement's 250 reserve
        remains.

        Design: Difficulty/transitive_cascade/campaign_pause_cascade_depth2_rejects_proposed
        """
        publisher, show, episode, advertiser, campaign, inserted, proposed = \
            self._setup_paused_with_mixed_placements()
        adv_headers = make_advertiser_headers(advertiser["id"])
        api.pause_ad_campaign(campaign["id"], adv_headers)
        c = validate_success(api.get_ad_campaign(campaign["id"], adv_headers), 200)
        assert c["reserved_budget_cents"] == 250


# ============================================================================
# Difficulty: compensating_invariant / campaign_budget_conserved_reserve_then_cancel
# ============================================================================
class TestBudgetConservation:
    def test_cancel_releases_reserve(self, api):
        """PRD §3.6: "Cancellation moves the placement to the terminal CANCELLED state, releases
        the reserve (the campaign's reserved_budget_cents decreases by estimated_cost_cents and
        available_budget_cents is recomputed)". Insert reserves 250; cancel restores reserved 0.

        Design: Difficulty/compensating_invariant/campaign_budget_conserved_reserve_then_cancel
        """
        publisher, show, episode = setup_monetized_published_episode()
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 100000, "bid_cpm_cents": 50000})
        placement = create_inserted_placement(advertiser, campaign, episode, forecast_impressions=5)
        adv_headers = make_advertiser_headers(advertiser["id"])
        cancelled = validate_success(api.cancel_ad_placement(placement["id"], adv_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        c = validate_success(api.get_ad_campaign(campaign["id"], adv_headers), 200)
        assert c["reserved_budget_cents"] == 0
        assert c["spent_budget_cents"] == 0

    def test_budget_invariant_holds_after_reserve_then_cancel(self, api):
        """PRD §3.4: "The platform holds the invariant that budget_cents always equals the sum of
        available, reserved, and spent." After reserve-then-cancel, available returns to the full
        100000 and the invariant holds.

        Design: Difficulty/compensating_invariant/campaign_budget_conserved_reserve_then_cancel
        """
        publisher, show, episode = setup_monetized_published_episode()
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 100000, "bid_cpm_cents": 50000})
        placement = create_inserted_placement(advertiser, campaign, episode, forecast_impressions=5)
        adv_headers = make_advertiser_headers(advertiser["id"])
        api.cancel_ad_placement(placement["id"], adv_headers)
        c = validate_success(api.get_ad_campaign(campaign["id"], adv_headers), 200)
        assert c["available_budget_cents"] == 100000
        assert c["budget_cents"] == (
            c["available_budget_cents"] + c["reserved_budget_cents"] + c["spent_budget_cents"])


# ============================================================================
# Difficulty: compensating_invariant / episode_ad_slots_conserved_fill_then_cancel
# ============================================================================
class TestSlotConservation:
    def test_cancel_frees_slot(self, api):
        """PRD §3.6: "A placement can be cancelled by the owning Advertiser ... and recomputes the
        episode's filled_slots, available_slots, and fill_rate." On a 2-slot episode, insert then
        cancel returns filled_slots 0 and available_slots 2.

        Design: Difficulty/compensating_invariant/episode_ad_slots_conserved_fill_then_cancel
        """
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 2, "offered_positions": ["PRE_ROLL"]})
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        placement = create_inserted_placement(advertiser, campaign, episode, forecast_impressions=5)
        adv_headers = make_advertiser_headers(advertiser["id"])
        api.cancel_ad_placement(placement["id"], adv_headers)
        pub_headers = make_publisher_headers(publisher["id"])
        ep = validate_success(api.get_episode(episode["id"], pub_headers), 200)
        assert ep["filled_slots"] == 0
        assert ep["available_slots"] == 2

    def test_fill_rate_zero_after_cancel(self, api):
        """PRD §3.2: "fill rate is computed by counting the placements on the episode whose status
        is INSERTED or DELIVERED to get filled slots ... dividing filled slots by total slots".
        After the only INSERTED placement is cancelled, fill_rate is 0.0.

        Design: Difficulty/compensating_invariant/episode_ad_slots_conserved_fill_then_cancel
        """
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 2, "offered_positions": ["PRE_ROLL"]})
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        placement = create_inserted_placement(advertiser, campaign, episode, forecast_impressions=5)
        adv_headers = make_advertiser_headers(advertiser["id"])
        api.cancel_ad_placement(placement["id"], adv_headers)
        pub_headers = make_publisher_headers(publisher["id"])
        ep = validate_success(api.get_episode(episode["id"], pub_headers), 200)
        assert ep["fill_rate"] == 0.0


# ============================================================================
# Difficulty: boundary_precision_check / budget_exhaustion_at_exactly_zero_boundary
# ============================================================================
class TestBudgetExhaustionBoundary:
    def test_insert_to_exactly_zero_exhausts_campaign(self, api):
        """PRD §3.6: "If, at the moment an insert confirms, the campaign's available_budget_cents
        is exactly zero, the campaign automatically transitions ACTIVE -> EXHAUSTED." Budget 250,
        single reserve 250 drives available to exactly 0.

        Design: Difficulty/boundary_precision_check/budget_exhaustion_at_exactly_zero_boundary
        """
        publisher, show, episode = setup_monetized_published_episode()
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 250, "bid_cpm_cents": 50000})
        placement = create_inserted_placement(advertiser, campaign, episode, forecast_impressions=5)
        assert placement["status"] == "INSERTED"
        adv_headers = make_advertiser_headers(advertiser["id"])
        c = validate_success(api.get_ad_campaign(campaign["id"], adv_headers), 200)
        assert c["available_budget_cents"] == 0
        assert c["status"] == "EXHAUSTED"

    def test_insert_above_zero_does_not_exhaust(self, api):
        """PRD §3.6: "If, at the moment an insert confirms, the campaign's available_budget_cents
        is exactly zero, the campaign automatically transitions ACTIVE -> EXHAUSTED." With budget
        251 the post-insert available is 1 (>0), so the campaign stays ACTIVE.

        Design: Difficulty/boundary_precision_check/budget_exhaustion_at_exactly_zero_boundary
        """
        publisher, show, episode = setup_monetized_published_episode()
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 251, "bid_cpm_cents": 50000})
        placement = create_inserted_placement(advertiser, campaign, episode, forecast_impressions=5)
        assert placement["status"] == "INSERTED"
        adv_headers = make_advertiser_headers(advertiser["id"])
        c = validate_success(api.get_ad_campaign(campaign["id"], adv_headers), 200)
        assert c["available_budget_cents"] == 1
        assert c["status"] == "ACTIVE"


# ============================================================================
# Difficulty: boundary_precision_check / fill_rate_empty_slot_set_zero_via_episode_read
# ============================================================================
class TestFillRateZeroDenominator:
    def test_zero_total_slots_yields_zero_fill_rate(self, api):
        """PRD §3.2: "fill_rate ... is defined to be 0.0 whenever total_ad_slots is zero so that an
        empty episode never divides by zero."

        Design: Difficulty/boundary_precision_check/fill_rate_empty_slot_set_zero_via_episode_read
        """
        publisher = create_publisher()
        show = create_active_show(publisher, category="NEWS")
        episode = get_success_data(api_client.create_episode(
            {"show_id": show["id"], "title": "EpZero", "total_ad_slots": 0,
             "offered_positions": []}, make_publisher_headers(publisher["id"])))
        pub_headers = make_publisher_headers(publisher["id"])
        ep = validate_success(api.get_episode(episode["id"], pub_headers), 200)
        assert ep["fill_rate"] == 0.0

    def test_zero_total_slots_filled_and_available_zero(self, api):
        """PRD §3.2: "Its available_slots is total_ad_slots minus filled_slots." On a zero-slot
        episode both filled_slots and available_slots are 0.

        Design: Difficulty/boundary_precision_check/fill_rate_empty_slot_set_zero_via_episode_read
        """
        publisher = create_publisher()
        show = create_active_show(publisher, category="NEWS")
        episode = get_success_data(api_client.create_episode(
            {"show_id": show["id"], "title": "EpZero", "total_ad_slots": 0,
             "offered_positions": []}, make_publisher_headers(publisher["id"])))
        pub_headers = make_publisher_headers(publisher["id"])
        ep = validate_success(api.get_episode(episode["id"], pub_headers), 200)
        assert ep["filled_slots"] == 0
        assert ep["available_slots"] == 0
