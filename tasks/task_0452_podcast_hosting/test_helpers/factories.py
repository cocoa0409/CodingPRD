"""Payload factories — one per entity, input fields only (Podcast Hosting & Monetization API).

Only fields the client supplies on create/transition are included. System/computed fields
(status, version, episode_count, ledger fields, counted, access_token, external_ref, etc.)
are server-managed and never sent. Optional fields with PRD defaults (monetization_enabled,
premium_targeting, revenue_share_pct, offset_ms) are omitted unless overridden.
"""

DEFAULT_FLIGHT_START = "2026-01-01T00:00:00Z"
DEFAULT_FLIGHT_END = "2026-12-31T00:00:00Z"


def create_publisher_payload(**overrides) -> dict:
    defaults = {"name": "Test Publisher", "payout_email": "publisher@example.com"}
    defaults.update(overrides)
    return defaults


def create_advertiser_payload(**overrides) -> dict:
    defaults = {"name": "Test Advertiser", "billing_email": "advertiser@example.com"}
    defaults.update(overrides)
    return defaults


def create_listener_payload(**overrides) -> dict:
    defaults = {"email": "listener@example.com", "display_name": "Test Listener"}
    defaults.update(overrides)
    return defaults


def create_show_payload(publisher_id: str, **overrides) -> dict:
    defaults = {"publisher_id": publisher_id, "title": "Test Show", "category": "TECH"}
    defaults.update(overrides)
    return defaults


def create_episode_payload(show_id: str, **overrides) -> dict:
    defaults = {
        "show_id": show_id,
        "title": "Test Episode",
        "total_ad_slots": 0,
        "offered_positions": [],
    }
    defaults.update(overrides)
    return defaults


def create_media_asset_payload(episode_id: str, **overrides) -> dict:
    defaults = {
        "episode_id": episode_id,
        "source_filename": "audio.wav",
        "source_duration_ms": 600000,
    }
    defaults.update(overrides)
    return defaults


def create_feed_payload(show_id: str, **overrides) -> dict:
    defaults = {"show_id": show_id, "visibility": "PUBLIC"}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(listener_id: str, show_id: str, **overrides) -> dict:
    defaults = {
        "listener_id": listener_id,
        "show_id": show_id,
        "price_cents": 500,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-01-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(show_id: str, **overrides) -> dict:
    defaults = {"show_id": show_id, "channel": "APPLE"}
    defaults.update(overrides)
    return defaults


def create_ad_campaign_payload(advertiser_id: str, **overrides) -> dict:
    defaults = {
        "advertiser_id": advertiser_id,
        "name": "Test Campaign",
        "budget_cents": 1_000_000,
        "bid_cpm_cents": 50000,
        "targeting_category": "TECH",
        "flight_start": DEFAULT_FLIGHT_START,
        "flight_end": DEFAULT_FLIGHT_END,
    }
    defaults.update(overrides)
    return defaults


def create_ad_placement_payload(campaign_id: str, episode_id: str, expected_campaign_version,
                                **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "episode_id": episode_id,
        "position": "PRE_ROLL",
        "ad_duration_ms": 30000,
        "forecast_impressions": 5,
        "expected_campaign_version": expected_campaign_version,
    }
    defaults.update(overrides)
    return defaults


def create_download_event_payload(episode_id: str, **overrides) -> dict:
    defaults = {
        "episode_id": episode_id,
        "client_ip_hash": "hash-1",
        "user_agent": "test-agent",
        "bytes_served": 2_000_000,
        "event_at": "2026-01-01T01:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_payout_statement_payload(publisher_id: str, **overrides) -> dict:
    defaults = {
        "publisher_id": publisher_id,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
