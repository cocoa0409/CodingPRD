"""Composite setup helpers for multi-step test prerequisites (Podcast Hosting & Monetization API).

Most interesting claims require walking the system through many steps before the behavior
under test is reachable (e.g. publisher -> show -> activate -> episode -> upload media ->
transcode to READY -> publish; advertiser -> campaign -> activate -> placement -> insert ->
downloads -> reconcile). These helpers encapsulate those preambles.

All helpers use get_success_data() (the lenient 2xx validator) for setup calls so a broken
precondition surfaces as a clear "Setup failed" error rather than a confusing downstream
assertion. The harness restarts the server (empty DB) before every test, so each helper builds
its preconditions from scratch using only PRD-declared endpoints.

Identity threading (PRD §2.1): Publisher / Advertiser / Listener are entity-backed. Every
ownership-gated call here uses make_<role>_headers(actor_id), never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_publisher_payload,
    create_advertiser_payload,
    create_listener_payload,
    create_show_payload,
    create_episode_payload,
    create_media_asset_payload,
    create_feed_payload,
    create_subscription_payload,
    create_distribution_payload,
    create_ad_campaign_payload,
    create_ad_placement_payload,
    create_download_event_payload,
    create_payout_statement_payload,
)
from .test_users import (
    TEST_USERS,
    make_publisher_headers,
    make_advertiser_headers,
    make_listener_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Clock control ────────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Advance the logical clock; fires due episode publishes / subscription transitions."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 0: Actor registration ───────────────────────────────────────────────
def create_publisher(**overrides):
    """Register a publisher. Returns the publisher dict."""
    return get_success_data(api_client.create_publisher(create_publisher_payload(**overrides), ADMIN))


def create_advertiser(**overrides):
    """Register an advertiser. Returns the advertiser dict."""
    return get_success_data(api_client.create_advertiser(create_advertiser_payload(**overrides), ADMIN))


def create_listener(**overrides):
    """Register a listener. Returns the listener dict."""
    return get_success_data(api_client.create_listener(create_listener_payload(**overrides), ADMIN))


# ─── Tier 1: Show state progression ───────────────────────────────────────────
def create_show(publisher, **overrides):
    """Create a DRAFT show owned by `publisher`. Returns the show dict."""
    headers = make_publisher_headers(publisher["id"])
    return get_success_data(api_client.create_show(create_show_payload(publisher["id"], **overrides), headers))


def create_active_show(publisher, **overrides):
    """Create + activate a show. Returns the activated show dict."""
    show = create_show(publisher, **overrides)
    headers = make_publisher_headers(publisher["id"])
    return get_success_data(api_client.activate_show(show["id"], headers))


def create_publisher_and_active_show(show_overrides=None):
    """Register a publisher and create one ACTIVE show. Returns (publisher, show)."""
    publisher = create_publisher()
    show = create_active_show(publisher, **(show_overrides or {}))
    return publisher, show


# ─── Tier 2: Episode + media to READY ─────────────────────────────────────────
def create_episode(publisher, show, **overrides):
    """Create a DRAFT episode under `show`. Returns the episode dict."""
    headers = make_publisher_headers(publisher["id"])
    return get_success_data(api_client.create_episode(create_episode_payload(show["id"], **overrides), headers))


def transcode_to_ready(publisher, episode, output_duration_ms=600000, source_duration_ms=600000):
    """Upload media and drive transcode SUCCESS so episode.media_status == READY.
    Returns the READY media asset dict."""
    pub_headers = make_publisher_headers(publisher["id"])
    asset = get_success_data(api_client.create_media_asset(
        create_media_asset_payload(episode["id"], source_duration_ms=source_duration_ms), pub_headers))
    api_client.transcode_start(asset["id"], ADMIN)
    return get_success_data(api_client.transcode_result(
        asset["id"], {"outcome": "SUCCESS", "output_duration_ms": output_duration_ms}, ADMIN))


def create_published_ready_episode(publisher, show, **ep_overrides):
    """Create an episode, transcode media to READY, publish it. Returns the published episode dict.

    Requires `show` to be ACTIVE. Returns the episode after PUBLISHED.
    """
    pub_headers = make_publisher_headers(publisher["id"])
    episode = create_episode(publisher, show, **ep_overrides)
    transcode_to_ready(publisher, episode)
    return get_success_data(api_client.publish_episode(episode["id"], pub_headers))


# ─── Tier 3: Campaign progression ─────────────────────────────────────────────
def create_advertiser_and_active_campaign(campaign_overrides=None):
    """Register an advertiser and create one ACTIVE campaign.
    Returns (advertiser, campaign) where campaign is the activated dict (current version)."""
    advertiser = create_advertiser()
    adv_headers = make_advertiser_headers(advertiser["id"])
    campaign = get_success_data(api_client.create_ad_campaign(
        create_ad_campaign_payload(advertiser["id"], **(campaign_overrides or {})), adv_headers))
    campaign = get_success_data(api_client.activate_ad_campaign(campaign["id"], adv_headers))
    return advertiser, campaign


def current_campaign_version(advertiser, campaign):
    """Re-read the campaign and return its current version (for OCC threading)."""
    adv_headers = make_advertiser_headers(advertiser["id"])
    return get_success_data(api_client.get_ad_campaign(campaign["id"], adv_headers))["version"]


def create_proposed_placement(advertiser, campaign, episode, **overrides):
    """Create a PROPOSED placement against `campaign` on `episode`, reading the live campaign
    version for the OCC field. Returns the created placement dict."""
    adv_headers = make_advertiser_headers(advertiser["id"])
    version = current_campaign_version(advertiser, campaign)
    return get_success_data(api_client.create_ad_placement(
        create_ad_placement_payload(campaign["id"], episode["id"], version, **overrides), adv_headers))


def create_inserted_placement(advertiser, campaign, episode, **overrides):
    """Create + insert a placement. Returns the INSERTED placement dict."""
    adv_headers = make_advertiser_headers(advertiser["id"])
    placement = create_proposed_placement(advertiser, campaign, episode, **overrides)
    return get_success_data(api_client.insert_ad_placement(placement["id"], adv_headers))


# ─── Tier 4: Full booking + delivery scenarios ────────────────────────────────
def setup_monetized_published_episode(show_overrides=None, episode_overrides=None):
    """Publisher + ACTIVE monetized TECH show + one PUBLISHED+READY episode.

    Returns (publisher, show, episode). Defaults: category TECH, monetization_enabled True,
    episode total_ad_slots 1 offering PRE_ROLL.
    """
    s_over = {"category": "TECH", "monetization_enabled": True}
    s_over.update(show_overrides or {})
    publisher, show = create_publisher_and_active_show(show_overrides=s_over)
    e_over = {"total_ad_slots": 1, "offered_positions": ["PRE_ROLL"]}
    e_over.update(episode_overrides or {})
    episode = create_published_ready_episode(publisher, show, **e_over)
    return publisher, show, episode


def add_counted_downloads(episode, placement, count, event_at="2026-01-01T01:00:00Z",
                          ip_prefix="dl"):
    """Ingest `count` counted DownloadEvents (>= IAB min) crediting `placement`.
    Each increments placement.delivered_impressions by one."""
    for i in range(count):
        get_success_data(api_client.create_download_event(
            create_download_event_payload(
                episode["id"],
                placement_id=placement["id"],
                client_ip_hash=f"{ip_prefix}{i}",
                bytes_served=2_000_000,
                event_at=event_at,
            ),
            ADMIN,
        ))


def deliver_placement(advertiser, campaign, episode, forecast_impressions, delivered,
                      event_at="2026-01-01T01:00:00Z", ip_prefix="d", **placement_overrides):
    """Create -> insert a placement, ingest `delivered` counted downloads, reconcile to DELIVERED.

    Returns the DELIVERED placement dict (re-read so final_cost_cents is populated).
    """
    adv_headers = make_advertiser_headers(advertiser["id"])
    placement = create_inserted_placement(
        advertiser, campaign, episode, forecast_impressions=forecast_impressions, **placement_overrides)
    add_counted_downloads(episode, placement, delivered, event_at=event_at, ip_prefix=ip_prefix)
    api_client.reconcile_ad_placement(placement["id"], ADMIN)
    return get_success_data(api_client.get_ad_placement(placement["id"], adv_headers))


# ─── Tier 5: Feeds / Subscriptions / Distribution ─────────────────────────────
def create_feed(publisher, show, visibility="PUBLIC"):
    """Create an ENABLED feed for `show`. Returns the feed dict."""
    headers = make_publisher_headers(publisher["id"])
    return get_success_data(api_client.create_feed(create_feed_payload(show["id"], visibility=visibility), headers))


def create_pending_subscription(listener, show, **overrides):
    """Create a PENDING subscription for `listener` on `show`. Returns the subscription dict."""
    headers = make_listener_headers(listener["id"])
    return get_success_data(api_client.create_subscription(
        create_subscription_payload(listener["id"], show["id"], **overrides), headers))


def create_active_subscription(listener, show, **overrides):
    """Create + activate a subscription. Requires `show` to have a PRIVATE ENABLED feed.
    Returns the ACTIVE subscription dict (with access_token)."""
    headers = make_listener_headers(listener["id"])
    sub = create_pending_subscription(listener, show, **overrides)
    return get_success_data(api_client.activate_subscription(sub["id"], headers))


def create_pending_distribution(publisher, show, channel="APPLE"):
    """Submit a PENDING distribution for `show`. Returns the distribution dict."""
    headers = make_publisher_headers(publisher["id"])
    return get_success_data(api_client.create_distribution(
        create_distribution_payload(show["id"], channel=channel), headers))
