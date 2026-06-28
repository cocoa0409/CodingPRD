"""State-machine behaviour: transcode cycle, parallel episode axes, cross-entity gates,
invalid transitions, scheduling, and guarded transitions.

Covers difficulty rules non_linear_state_machine and cross_entity_state_dependency, plus
corner state_machines instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_publisher_headers,
    make_advertiser_headers,
    make_listener_headers,
    TEST_USERS,
    create_publisher,
    create_show,
    create_active_show,
    create_episode,
    transcode_to_ready,
    create_published_ready_episode,
    create_advertiser_and_active_campaign,
    create_proposed_placement,
    create_active_subscription,
    create_feed,
    create_pending_subscription,
    create_pending_distribution,
    create_inserted_placement,
    set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ============================================================================
# Difficulty: non_linear_state_machine / media_asset_transcode_failure_retry_cycle
# ============================================================================
class TestTranscodeRetryCycle:
    def test_failure_then_retry_then_success_reaches_ready(self, api):
        """PRD §3.2: "A FAILED asset can be retried back into TRANSCODING by starting transcoding
        again ... a successful retry increments transcode_attempts and returns the episode to
        PROCESSING. The asset reaches its terminal state at READY".

        Design: Difficulty/non_linear_state_machine/media_asset_transcode_failure_retry_cycle
        """
        publisher = create_publisher()
        show = create_active_show(publisher, category="NEWS")
        episode = create_episode(publisher, show, total_ad_slots=0, offered_positions=[])
        pub_headers = make_publisher_headers(publisher["id"])
        asset = get_success_data(api.create_media_asset(
            {"episode_id": episode["id"], "source_filename": "m.wav",
             "source_duration_ms": 300000}, pub_headers))
        api.transcode_start(asset["id"], ADMIN)
        api.transcode_result(asset["id"], {"outcome": "FAILURE"}, ADMIN)
        api.transcode_start(asset["id"], ADMIN)  # retry
        result = validate_success(api.transcode_result(
            asset["id"], {"outcome": "SUCCESS", "output_duration_ms": 300000}, ADMIN), 200)
        assert result["status"] == "READY"

    def test_transcode_attempts_increments_across_retry(self, api):
        """PRD §3.2: "A PlatformAdmin starts transcoding ... this increments transcode_attempts
        by one" and a "successful retry increments transcode_attempts" — the FAILED->retry cycle
        leaves transcode_attempts at 2, and the episode media reaches READY with duration copied.

        Design: Difficulty/non_linear_state_machine/media_asset_transcode_failure_retry_cycle
        """
        publisher = create_publisher()
        show = create_active_show(publisher, category="NEWS")
        episode = create_episode(publisher, show, total_ad_slots=0, offered_positions=[])
        pub_headers = make_publisher_headers(publisher["id"])
        asset = get_success_data(api.create_media_asset(
            {"episode_id": episode["id"], "source_filename": "m.wav",
             "source_duration_ms": 300000}, pub_headers))
        api.transcode_start(asset["id"], ADMIN)
        api.transcode_result(asset["id"], {"outcome": "FAILURE"}, ADMIN)
        api.transcode_start(asset["id"], ADMIN)
        result = validate_success(api.transcode_result(
            asset["id"], {"outcome": "SUCCESS", "output_duration_ms": 300000}, ADMIN), 200)
        assert result["transcode_attempts"] == 2
        ep = validate_success(api.get_episode(episode["id"], pub_headers), 200)
        assert ep["media_status"] == "READY"
        assert ep["duration_ms"] == 300000


# ============================================================================
# Difficulty: non_linear_state_machine / episode_parallel_axes_media_and_publish_independent
# ============================================================================
class TestEpisodeParallelAxes:
    def test_publish_axis_scheduled_while_media_advances(self, api):
        """PRD §3.2: "These two status fields are genuinely independent axes: the publish axis
        tracks distribution while the media axis tracks transcoding, and they advance on their own
        triggers." A SCHEDULED episode keeps publish_status SCHEDULED while media reaches READY.

        Design: Difficulty/non_linear_state_machine/episode_parallel_axes_media_and_publish_independent
        """
        set_clock("2026-02-01T00:00:00Z")
        publisher = create_publisher()
        show = create_active_show(publisher, category="NEWS")
        episode = create_episode(publisher, show, total_ad_slots=0, offered_positions=[])
        pub_headers = make_publisher_headers(publisher["id"])
        api.schedule_episode(episode["id"], {"scheduled_publish_at": "2026-12-01T00:00:00Z"}, pub_headers)
        transcode_to_ready(publisher, episode, output_duration_ms=400000, source_duration_ms=400000)
        ep = validate_success(api.get_episode(episode["id"], pub_headers), 200)
        assert ep["publish_status"] == "SCHEDULED"

    def test_media_axis_reaches_ready_independent_of_publish(self, api):
        """PRD §3.2: "with a SUCCESS outcome the asset goes TRANSCODING -> READY ... sets the
        episode's media_status to READY". The media axis lands on READY even though the publish
        axis is still SCHEDULED.

        Design: Difficulty/non_linear_state_machine/episode_parallel_axes_media_and_publish_independent
        """
        set_clock("2026-02-01T00:00:00Z")
        publisher = create_publisher()
        show = create_active_show(publisher, category="NEWS")
        episode = create_episode(publisher, show, total_ad_slots=0, offered_positions=[])
        pub_headers = make_publisher_headers(publisher["id"])
        api.schedule_episode(episode["id"], {"scheduled_publish_at": "2026-12-01T00:00:00Z"}, pub_headers)
        transcode_to_ready(publisher, episode, output_duration_ms=400000, source_duration_ms=400000)
        ep = validate_success(api.get_episode(episode["id"], pub_headers), 200)
        assert ep["media_status"] == "READY"


# ============================================================================
# Difficulty: cross_entity_state_dependency / episode_publish_requires_show_active
# ============================================================================
class TestPublishRequiresShowActive:
    def test_publish_rejected_when_show_draft(self, api):
        """PRD §3.2: "Publishing requires that the episode's show is ACTIVE and that the episode's
        media_status is READY; either condition unmet rejects the publish with ERR_INVALID_STATE."
        Show still DRAFT, media READY => ERR_INVALID_STATE.

        Design: Difficulty/cross_entity_state_dependency/episode_publish_requires_show_active
        """
        publisher = create_publisher()
        show = create_show(publisher, category="TECH")  # never activated
        episode = create_episode(publisher, show, total_ad_slots=0, offered_positions=[])
        transcode_to_ready(publisher, episode)
        pub_headers = make_publisher_headers(publisher["id"])
        res = api.publish_episode(episode["id"], pub_headers)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_episode_stays_draft_after_rejected_publish(self, api):
        """PRD §3.2: "either condition unmet rejects the publish with ERR_INVALID_STATE." A
        rejected publish leaves the episode in its prior publish_status DRAFT.

        Design: Difficulty/cross_entity_state_dependency/episode_publish_requires_show_active
        """
        publisher = create_publisher()
        show = create_show(publisher, category="TECH")
        episode = create_episode(publisher, show, total_ad_slots=0, offered_positions=[])
        transcode_to_ready(publisher, episode)
        pub_headers = make_publisher_headers(publisher["id"])
        api.publish_episode(episode["id"], pub_headers)
        ep = validate_success(api.get_episode(episode["id"], pub_headers), 200)
        assert ep["publish_status"] == "DRAFT"


# ============================================================================
# Difficulty: cross_entity_state_dependency / placement_insert_requires_episode_published_and_ready
# ============================================================================
class TestInsertRequiresEpisodePublishedReady:
    def test_insert_rejected_when_episode_unpublished_draft(self, api):
        """PRD §3.6: "Insertion also requires the campaign to be ACTIVE, the episode to be
        PUBLISHED, and the episode's media to be READY; any of these unmet rejects the insert with
        ERR_INVALID_STATE." Episode media READY but never published (DRAFT) => ERR_INVALID_STATE.

        Design: Difficulty/cross_entity_state_dependency/placement_insert_requires_episode_published_and_ready
        """
        publisher = create_publisher()
        show = create_active_show(publisher, category="TECH", monetization_enabled=True)
        episode = create_episode(publisher, show, total_ad_slots=1, offered_positions=["PRE_ROLL"])
        transcode_to_ready(publisher, episode)  # media READY, publish_status still DRAFT
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        placement = create_proposed_placement(advertiser, campaign, episode, forecast_impressions=5)
        adv_headers = make_advertiser_headers(advertiser["id"])
        res = api.insert_ad_placement(placement["id"], adv_headers)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_placement_stays_proposed_after_rejected_insert(self, api):
        """PRD §3.6: "any of these unmet rejects the insert with ERR_INVALID_STATE." A rejected
        insert leaves the placement in PROPOSED.

        Design: Difficulty/cross_entity_state_dependency/placement_insert_requires_episode_published_and_ready
        """
        publisher = create_publisher()
        show = create_active_show(publisher, category="TECH", monetization_enabled=True)
        episode = create_episode(publisher, show, total_ad_slots=1, offered_positions=["PRE_ROLL"])
        transcode_to_ready(publisher, episode)
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        placement = create_proposed_placement(advertiser, campaign, episode, forecast_impressions=5)
        adv_headers = make_advertiser_headers(advertiser["id"])
        api.insert_ad_placement(placement["id"], adv_headers)
        refreshed = validate_success(api.get_ad_placement(placement["id"], adv_headers), 200)
        assert refreshed["status"] == "PROPOSED"


# ============================================================================
# Corner: state_machines
# ============================================================================
def test_activate_archived_show_returns_invalid_state(api):
    """PRD §3.1: "The owning Publisher archives a show from either DRAFT or ACTIVE, reaching the
    terminal ARCHIVED state". Activating from terminal ARCHIVED is not a defined transition and
    per §2.5 yields ERR_INVALID_STATE.

    Design: Corner/state_machines/activate_show_from_archived_returns_invalid_state
    """
    publisher = create_publisher()
    show = create_show(publisher, category="TECH")
    pub_headers = make_publisher_headers(publisher["id"])
    get_success_data(api.archive_show(show["id"], pub_headers))
    res = api.activate_show(show["id"], pub_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_subscription_twice_returns_invalid_state(api):
    """PRD §3.3: "The owning Listener cancels an ACTIVE or PAST_DUE subscription, moving it to the
    terminal CANCELLED state". A second cancel from terminal CANCELLED is undefined and per §2.5
    yields ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_subscription_twice_returns_invalid_state
    """
    publisher = create_publisher()
    show = create_active_show(publisher, category="BUSINESS")
    create_feed(publisher, show, visibility="PRIVATE")
    listener = get_success_data(api.create_listener(
        {"email": "lsc@x.com", "display_name": "LSc"}, ADMIN))
    sub = create_active_subscription(listener, show)
    lst_headers = make_listener_headers(listener["id"])
    get_success_data(api.cancel_subscription(sub["id"], lst_headers))
    res = api.cancel_subscription(sub["id"], lst_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_schedule_episode_at_clock_returns_schedule_in_past(api):
    """PRD §3.2: "this instant must be strictly after the current logical clock, and a value at or
    before the clock is rejected with ERR_SCHEDULE_IN_PAST." scheduled_publish_at equal to the
    clock (not strictly after) => ERR_SCHEDULE_IN_PAST.

    Design: Corner/state_machines/schedule_episode_in_past_returns_schedule_in_past
    """
    set_clock("2026-06-01T00:00:00Z")
    publisher = create_publisher()
    show = create_active_show(publisher, category="NEWS")
    episode = create_episode(publisher, show, total_ad_slots=0, offered_positions=[])
    pub_headers = make_publisher_headers(publisher["id"])
    res = api.schedule_episode(episode["id"], {"scheduled_publish_at": "2026-06-01T00:00:00Z"}, pub_headers)
    validate_error(res, "ERR_SCHEDULE_IN_PAST", expected_status=422)


def test_scheduled_episode_auto_publishes_when_clock_advances(api):
    """PRD §2.9: "Each SCHEDULED episode whose scheduled_publish_at is at or before the new clock
    value automatically publishes, provided its show is ACTIVE and its media is READY."

    Design: Corner/state_machines/scheduled_episode_auto_publishes_when_clock_advances
    """
    set_clock("2026-07-01T00:00:00Z")
    publisher = create_publisher()
    show = create_active_show(publisher, category="NEWS")
    episode = create_episode(publisher, show, total_ad_slots=0, offered_positions=[])
    transcode_to_ready(publisher, episode, output_duration_ms=100000, source_duration_ms=100000)
    pub_headers = make_publisher_headers(publisher["id"])
    api.schedule_episode(episode["id"], {"scheduled_publish_at": "2026-07-15T00:00:00Z"}, pub_headers)
    set_clock("2026-07-20T00:00:00Z")
    ep = validate_success(api.get_episode(episode["id"], pub_headers), 200)
    assert ep["publish_status"] == "PUBLISHED"


def test_archive_active_show_with_published_episode_rejected(api):
    """PRD §3.1: "Archiving a show that is ACTIVE is refused with ERR_SHOW_HAS_PUBLISHED_EPISODES
    when any episode of that show is still PUBLISHED".

    Design: Corner/state_machines/archive_active_show_with_published_episode_rejected
    """
    publisher = create_publisher()
    show = create_active_show(publisher, category="TECH")
    create_published_ready_episode(publisher, show, total_ad_slots=0, offered_positions=[])
    pub_headers = make_publisher_headers(publisher["id"])
    res = api.archive_show(show["id"], pub_headers)
    validate_error(res, "ERR_SHOW_HAS_PUBLISHED_EPISODES", expected_status=409)


def test_complete_campaign_with_open_placements_rejected(api):
    """PRD §3.4: "The owning Advertiser completes a campaign from either ACTIVE or EXHAUSTED ...
    but only when the campaign has no placements left in PROPOSED or INSERTED; an attempt with
    open placements is rejected with ERR_CAMPAIGN_HAS_OPEN_PLACEMENTS."

    Design: Corner/state_machines/complete_campaign_with_open_placements_rejected
    """
    publisher, show = create_publisher(), None
    show = create_active_show(publisher, category="TECH", monetization_enabled=True)
    episode = create_published_ready_episode(publisher, show, total_ad_slots=1, offered_positions=["PRE_ROLL"])
    advertiser, campaign = create_advertiser_and_active_campaign(
        campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
    create_inserted_placement(advertiser, campaign, episode, forecast_impressions=5)
    adv_headers = make_advertiser_headers(advertiser["id"])
    res = api.complete_ad_campaign(campaign["id"], adv_headers)
    validate_error(res, "ERR_CAMPAIGN_HAS_OPEN_PLACEMENTS", expected_status=409)


def test_transcode_result_from_uploaded_returns_invalid_state(api):
    """PRD §3.2: "The transcoder callback delivers the result: with a SUCCESS outcome the asset
    goes TRANSCODING -> READY". Submitting a result while the asset is still UPLOADED (transcode
    never started) is undefined and per §2.5 yields ERR_INVALID_STATE.

    Design: Corner/state_machines/transcode_result_from_uploaded_returns_invalid_state
    """
    publisher = create_publisher()
    show = create_show(publisher, category="TECH")
    episode = create_episode(publisher, show, total_ad_slots=0, offered_positions=[])
    pub_headers = make_publisher_headers(publisher["id"])
    asset = get_success_data(api.create_media_asset(
        {"episode_id": episode["id"], "source_filename": "mu.wav",
         "source_duration_ms": 100000}, pub_headers))
    res = api.transcode_result(asset["id"], {"outcome": "SUCCESS", "output_duration_ms": 100000}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_distribution_approve_without_public_feed_rejected(api):
    """PRD §3.3: "approval moves it PENDING -> LIVE and mints an external_ref ... but only when
    the show is ACTIVE and the show has a feed whose visibility is PUBLIC and whose status is
    ENABLED; otherwise approval is rejected with ERR_INVALID_STATE." Show has only a PRIVATE feed.

    Design: Corner/state_machines/distribution_approve_without_public_feed_rejected
    """
    publisher = create_publisher()
    show = create_active_show(publisher, category="TECH")
    create_feed(publisher, show, visibility="PRIVATE")
    distribution = create_pending_distribution(publisher, show, channel="APPLE")
    res = api.approve_distribution(distribution["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
