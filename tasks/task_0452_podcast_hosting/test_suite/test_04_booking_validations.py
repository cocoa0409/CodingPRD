"""Placement booking/insertion validations, validation precedence, and temporal overlap.

Covers difficulty rules priority_pair_validation_conflict and resource_temporal_overlap,
plus corner validations instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_publisher_headers,
    make_advertiser_headers,
    make_listener_headers,
    TEST_USERS,
    create_publisher,
    create_active_show,
    create_published_ready_episode,
    create_advertiser_and_active_campaign,
    create_proposed_placement,
    create_inserted_placement,
    current_campaign_version,
    setup_monetized_published_episode,
    create_feed,
    create_pending_subscription,
    create_active_subscription,
    api_client,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _new_campaign(advertiser, **overrides):
    """Create + activate a second campaign for the same advertiser. Returns the campaign dict."""
    adv_headers = make_advertiser_headers(advertiser["id"])
    payload = {
        "advertiser_id": advertiser["id"], "name": overrides.pop("name", "c2"),
        "budget_cents": 1_000_000, "bid_cpm_cents": 50000, "targeting_category": "TECH",
        "flight_start": "2026-01-01T00:00:00Z", "flight_end": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    c = get_success_data(api_client.create_ad_campaign(payload, adv_headers))
    return get_success_data(api_client.activate_ad_campaign(c["id"], adv_headers))


# ============================================================================
# Difficulty: priority_pair_validation_conflict / create_placement_state_beats_budget_fiscal
# ============================================================================
class TestStateBeatsFiscalOnCreate:
    def test_create_against_paused_campaign_returns_invalid_state(self, api):
        """PRD §2.5: "Only after these four gates does the system evaluate state legality, which
        yields ERR_INVALID_STATE ... and for placement creation, when the funding campaign is not
        ACTIVE. Business-specific rules (targeting, slots, budget, ...) are evaluated after the
        state gate". A PAUSED campaign whose estimate would also exceed budget returns the
        higher-priority ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/create_placement_state_beats_budget_fiscal
        """
        publisher, show, episode = setup_monetized_published_episode()
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 100, "bid_cpm_cents": 50000})
        adv_headers = make_advertiser_headers(advertiser["id"])
        get_success_data(api.pause_ad_campaign(campaign["id"], adv_headers))
        version = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
        res = api.create_ad_placement(
            {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "PRE_ROLL",
             "ad_duration_ms": 30000, "forecast_impressions": 5,
             "expected_campaign_version": version}, adv_headers)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_status_409_returned_not_budget_409(self, api):
        """PRD §2.5: "for placement creation, when the funding campaign is not ACTIVE" the state
        gate fires before "budget" business rules — so the conflict surfaces ERR_INVALID_STATE,
        not ERR_BUDGET_WOULD_EXCEED.

        Design: Difficulty/priority_pair_validation_conflict/create_placement_state_beats_budget_fiscal
        """
        publisher, show, episode = setup_monetized_published_episode()
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 100, "bid_cpm_cents": 50000})
        adv_headers = make_advertiser_headers(advertiser["id"])
        get_success_data(api.pause_ad_campaign(campaign["id"], adv_headers))
        version = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
        res = api.create_ad_placement(
            {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "PRE_ROLL",
             "ad_duration_ms": 30000, "forecast_impressions": 5,
             "expected_campaign_version": version}, adv_headers)
        error = validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        assert error["error_id"] != "ERR_BUDGET_WOULD_EXCEED"


# ============================================================================
# Difficulty: priority_pair_validation_conflict / insert_targeting_referential_beats_midroll_overlap_temporal
# ============================================================================
class TestTargetingBeatsOverlapOnInsert:
    def _setup_overlap_and_mismatch(self):
        """Episode total 3 offers MID_ROLL with an existing INSERTED MID_ROLL at [10000,15000);
        a second MID_ROLL at offset 11000 dur 5000 whose campaign targets COMEDY on a TECH show."""
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 3, "offered_positions": ["MID_ROLL"]})
        advertiser, match_campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        create_inserted_placement(advertiser, match_campaign, episode,
                                  position="MID_ROLL", offset_ms=10000, ad_duration_ms=5000,
                                  forecast_impressions=5)
        mismatch_campaign = _new_campaign(advertiser, name="cMis", targeting_category="COMEDY")
        trigger = create_proposed_placement(
            advertiser, mismatch_campaign, episode,
            position="MID_ROLL", offset_ms=11000, ad_duration_ms=5000, forecast_impressions=5)
        return advertiser, trigger

    def test_insert_returns_targeting_mismatch_over_overlap(self, api):
        """PRD §3.6: "Insertion enforces a battery of cross-entity gates evaluated in priority
        order. The episode's show category must equal the campaign's targeting_category, otherwise
        the insert is rejected with ERR_TARGETING_MISMATCH." Targeting (first gate) wins over the
        later MID_ROLL-overlap gate.

        Design: Difficulty/priority_pair_validation_conflict/insert_targeting_referential_beats_midroll_overlap_temporal
        """
        advertiser, trigger = self._setup_overlap_and_mismatch()
        adv_headers = make_advertiser_headers(advertiser["id"])
        res = api.insert_ad_placement(trigger["id"], adv_headers)
        validate_error(res, "ERR_TARGETING_MISMATCH", expected_status=422)

    def test_not_midroll_overlap_error(self, api):
        """PRD §3.6: "For a MID_ROLL placement, the interval ... must not overlap any existing
        INSERTED or DELIVERED MID_ROLL ... an overlap is rejected with ERR_MIDROLL_OVERLAP." This
        gate comes after the targeting gate, so the overlap error is NOT what surfaces.

        Design: Difficulty/priority_pair_validation_conflict/insert_targeting_referential_beats_midroll_overlap_temporal
        """
        advertiser, trigger = self._setup_overlap_and_mismatch()
        adv_headers = make_advertiser_headers(advertiser["id"])
        res = api.insert_ad_placement(trigger["id"], adv_headers)
        error = validate_error(res, "ERR_TARGETING_MISMATCH", expected_status=422)
        assert error["error_id"] != "ERR_MIDROLL_OVERLAP"


# ============================================================================
# Difficulty: resource_temporal_overlap / midroll_halfopen_plus_buffer_overlap_on_episode
# (also owns Corner errors/midroll_overlap_error_excluded — excluded stub, not translated)
# ============================================================================
class TestMidRollOverlap:
    def _setup_overlapping_midroll(self):
        """Episode offers MID_ROLL with an existing INSERTED MID_ROLL [10000,15000); a matching-
        category second MID_ROLL at offset 11000 dur 5000 (overlaps)."""
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 3, "offered_positions": ["MID_ROLL"]})
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        create_inserted_placement(advertiser, campaign, episode,
                                  position="MID_ROLL", offset_ms=10000, ad_duration_ms=5000,
                                  forecast_impressions=5)
        second = _new_campaign(advertiser, name="cT1b")
        trigger = create_proposed_placement(
            advertiser, second, episode,
            position="MID_ROLL", offset_ms=11000, ad_duration_ms=5000, forecast_impressions=5)
        return advertiser, trigger

    def test_overlapping_midroll_insert_rejected(self, api):
        """PRD §3.6: "For a MID_ROLL placement, the interval beginning at offset_ms and running for
        ad_duration_ms, extended by a one-second buffer on each side, must not overlap any existing
        INSERTED or DELIVERED MID_ROLL placement on the same episode; an overlap is rejected with
        ERR_MIDROLL_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/midroll_halfopen_plus_buffer_overlap_on_episode
        """
        advertiser, trigger = self._setup_overlapping_midroll()
        adv_headers = make_advertiser_headers(advertiser["id"])
        res = api.insert_ad_placement(trigger["id"], adv_headers)
        validate_error(res, "ERR_MIDROLL_OVERLAP", expected_status=409)

    def test_placement_stays_proposed_after_overlap_reject(self, api):
        """PRD §3.6: "an overlap is rejected with ERR_MIDROLL_OVERLAP." A rejected insert leaves
        the placement in PROPOSED (the PROPOSED -> INSERTED transition did not occur).

        Design: Difficulty/resource_temporal_overlap/midroll_halfopen_plus_buffer_overlap_on_episode
        """
        advertiser, trigger = self._setup_overlapping_midroll()
        adv_headers = make_advertiser_headers(advertiser["id"])
        api.insert_ad_placement(trigger["id"], adv_headers)
        refreshed = validate_success(api.get_ad_placement(trigger["id"], adv_headers), 200)
        assert refreshed["status"] == "PROPOSED"


# ============================================================================
# Difficulty: resource_temporal_overlap / subscription_closed_interval_overlap_on_listener_show
# (also owns Corner errors/subscription_period_overlap_error_excluded — excluded stub)
# ============================================================================
class TestSubscriptionPeriodOverlap:
    def _setup_overlapping_subscriptions(self):
        """Listener with an ACTIVE subscription [2026-01-01,2026-01-31] and a second PENDING
        subscription [2026-01-31,2026-02-28] sharing the endpoint date (closed-interval overlap)."""
        publisher = create_publisher()
        show = create_active_show(publisher, category="BUSINESS")
        create_feed(publisher, show, visibility="PRIVATE")
        listener = get_success_data(api_client.create_listener(
            {"email": "l1@x.com", "display_name": "L One"}, ADMIN))
        create_active_subscription(listener, show,
                                   period_start="2026-01-01T00:00:00Z", period_end="2026-01-31T00:00:00Z")
        second = create_pending_subscription(listener, show,
                                             period_start="2026-01-31T00:00:00Z",
                                             period_end="2026-02-28T00:00:00Z")
        return listener, second

    def test_overlapping_subscription_activation_rejected(self, api):
        """PRD §3.3: "the subscription's closed period [period_start, period_end] must not overlap
        any other subscription for the same listener_id and show_id that is currently ACTIVE or
        PAST_DUE, otherwise the activation is rejected with ERR_SUBSCRIPTION_PERIOD_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/subscription_closed_interval_overlap_on_listener_show
        """
        listener, second = self._setup_overlapping_subscriptions()
        lst_headers = make_listener_headers(listener["id"])
        res = api.activate_subscription(second["id"], lst_headers)
        validate_error(res, "ERR_SUBSCRIPTION_PERIOD_OVERLAP", expected_status=409)

    def test_overlapping_subscription_stays_pending(self, api):
        """PRD §3.3: "the activation is rejected with ERR_SUBSCRIPTION_PERIOD_OVERLAP." A rejected
        activation leaves the second subscription in PENDING.

        Design: Difficulty/resource_temporal_overlap/subscription_closed_interval_overlap_on_listener_show
        """
        listener, second = self._setup_overlapping_subscriptions()
        lst_headers = make_listener_headers(listener["id"])
        api.activate_subscription(second["id"], lst_headers)
        refreshed = validate_success(api.get_subscription(second["id"], lst_headers), 200)
        assert refreshed["status"] == "PENDING"


# ============================================================================
# Corner: validations
# ============================================================================
def test_create_placement_position_not_offered(api):
    """PRD §3.5: "The platform first checks, in priority order, that the requested position is a
    member of the episode's offered_positions, rejecting with ERR_POSITION_NOT_OFFERED if not."

    Design: Corner/validations/insert_position_not_offered_returns_position_not_offered
    """
    publisher, show, episode = setup_monetized_published_episode(
        episode_overrides={"total_ad_slots": 1, "offered_positions": ["PRE_ROLL"]})
    advertiser, campaign = create_advertiser_and_active_campaign(
        campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
    adv_headers = make_advertiser_headers(advertiser["id"])
    version = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
    res = api.create_ad_placement(
        {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "MID_ROLL",
         "offset_ms": 5000, "ad_duration_ms": 5000, "forecast_impressions": 5,
         "expected_campaign_version": version}, adv_headers)
    validate_error(res, "ERR_POSITION_NOT_OFFERED", expected_status=422)


def test_insert_monetization_disabled(api):
    """PRD §3.6: "The episode's show must have monetization_enabled set to true, otherwise the
    insert is rejected with ERR_MONETIZATION_DISABLED."

    Design: Corner/validations/insert_monetization_disabled_returns_monetization_disabled
    """
    publisher, show, episode = setup_monetized_published_episode(
        show_overrides={"category": "TECH", "monetization_enabled": False},
        episode_overrides={"total_ad_slots": 1, "offered_positions": ["PRE_ROLL"]})
    advertiser, campaign = create_advertiser_and_active_campaign(
        campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
    placement = create_proposed_placement(advertiser, campaign, episode, forecast_impressions=5)
    adv_headers = make_advertiser_headers(advertiser["id"])
    res = api.insert_ad_placement(placement["id"], adv_headers)
    validate_error(res, "ERR_MONETIZATION_DISABLED", expected_status=409)


def test_insert_no_available_slot(api):
    """PRD §3.6: "The episode must have an available slot — available_slots greater than zero —
    otherwise the insert is rejected with ERR_NO_AVAILABLE_SLOT." A 1-slot episode already filled
    by one INSERTED placement rejects a second insert.

    Design: Corner/validations/insert_no_available_slot_returns_no_available_slot
    """
    publisher, show, episode = setup_monetized_published_episode(
        episode_overrides={"total_ad_slots": 1, "offered_positions": ["PRE_ROLL", "POST_ROLL"]})
    advertiser, campaign = create_advertiser_and_active_campaign(
        campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
    create_inserted_placement(advertiser, campaign, episode, position="PRE_ROLL", forecast_impressions=5)
    second = create_proposed_placement(advertiser, campaign, episode, position="POST_ROLL",
                                       forecast_impressions=5)
    adv_headers = make_advertiser_headers(advertiser["id"])
    res = api.insert_ad_placement(second["id"], adv_headers)
    validate_error(res, "ERR_NO_AVAILABLE_SLOT", expected_status=409)


def test_activate_subscription_without_private_feed(api):
    """PRD §3.3: "the target show must have a feed whose visibility is PRIVATE and whose status is
    ENABLED, otherwise the activation is rejected with ERR_NO_PRIVATE_FEED." Show has only a
    PUBLIC feed.

    Design: Corner/validations/activate_subscription_without_private_feed_returns_no_private_feed
    """
    publisher = create_publisher()
    show = create_active_show(publisher, category="BUSINESS")
    create_feed(publisher, show, visibility="PUBLIC")
    listener = get_success_data(api.create_listener({"email": "lnf@x.com", "display_name": "LNf"}, ADMIN))
    sub = create_pending_subscription(listener, show)
    lst_headers = make_listener_headers(listener["id"])
    res = api.activate_subscription(sub["id"], lst_headers)
    validate_error(res, "ERR_NO_PRIVATE_FEED", expected_status=409)


def test_download_private_only_without_access(api):
    """PRD §3.7: "when the downloaded episode belongs to a show whose only feed is PRIVATE, the
    request must present a valid access_token from a subscription that is ACTIVE for the listener;
    absent that, the ingestion is rejected with ERR_NO_PRIVATE_ACCESS."

    Design: Corner/validations/download_private_only_without_access_returns_no_private_access
    """
    publisher = create_publisher()
    show = create_active_show(publisher, category="TECH")
    create_feed(publisher, show, visibility="PRIVATE")
    episode = create_published_ready_episode(publisher, show, total_ad_slots=0, offered_positions=[])
    listener = get_success_data(api.create_listener({"email": "lpa@x.com", "display_name": "LPa"}, ADMIN))
    lst_headers = make_listener_headers(listener["id"])
    res = api.create_download_event(
        {"episode_id": episode["id"], "client_ip_hash": "pa1", "user_agent": "ua",
         "bytes_served": 2_000_000, "event_at": "2026-01-01T04:00:00Z"}, lst_headers)
    validate_error(res, "ERR_NO_PRIVATE_ACCESS", expected_status=403)


def test_insert_targeting_mismatch(api):
    """PRD §3.6: "The episode's show category must equal the campaign's targeting_category,
    otherwise the insert is rejected with ERR_TARGETING_MISMATCH." Campaign targets NEWS, show is
    TECH, with no overlapping mid-roll so the rule is isolated.

    Design: Corner/validations/insert_targeting_mismatch_returns_targeting_mismatch
    """
    publisher, show, episode = setup_monetized_published_episode(
        episode_overrides={"total_ad_slots": 1, "offered_positions": ["PRE_ROLL"]})
    advertiser, campaign = create_advertiser_and_active_campaign(
        campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000,
                            "targeting_category": "NEWS"})
    placement = create_proposed_placement(advertiser, campaign, episode, forecast_impressions=5)
    adv_headers = make_advertiser_headers(advertiser["id"])
    res = api.insert_ad_placement(placement["id"], adv_headers)
    validate_error(res, "ERR_TARGETING_MISMATCH", expected_status=422)


def test_create_placement_budget_would_exceed(api):
    """PRD §3.5: "The resulting estimated_cost_cents must not exceed the campaign's
    available_budget_cents at create time; if it would, the create is rejected with
    ERR_BUDGET_WOULD_EXCEED." Estimate 250 > available 100 on an ACTIVE campaign.

    Design: Corner/validations/create_placement_budget_would_exceed_returns_budget_would_exceed
    """
    publisher, show, episode = setup_monetized_published_episode(
        episode_overrides={"total_ad_slots": 1, "offered_positions": ["PRE_ROLL"]})
    advertiser, campaign = create_advertiser_and_active_campaign(
        campaign_overrides={"budget_cents": 100, "bid_cpm_cents": 50000})
    adv_headers = make_advertiser_headers(advertiser["id"])
    version = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
    res = api.create_ad_placement(
        {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "PRE_ROLL",
         "ad_duration_ms": 30000, "forecast_impressions": 5,
         "expected_campaign_version": version}, adv_headers)
    validate_error(res, "ERR_BUDGET_WOULD_EXCEED", expected_status=409)
