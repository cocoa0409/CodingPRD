"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from . import constants as C


def create_channel_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Channel",
        "genre": "movies",
        "timezone": "UTC",
    }
    defaults.update(overrides)
    return defaults


def create_content_asset_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Movie",
        "content_type": "MOVIE",
        "runtime_seconds": 540,
        "rating": "PG",
        "genre": "movies",
    }
    defaults.update(overrides)
    return defaults


def create_rights_grant_payload(channel_id, content_id, **overrides) -> dict:
    defaults = {
        "channel_id": channel_id,
        "content_id": content_id,
        "window_start_utc": C.GRANT_WINDOW_START,
        "window_end_utc": C.GRANT_WINDOW_END,
        "max_plays": 10,
    }
    defaults.update(overrides)
    return defaults


def create_playlist_loop_payload(channel_id, **overrides) -> dict:
    defaults = {
        "channel_id": channel_id,
        "broadcast_date": C.BROADCAST_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_ad_campaign_payload(**overrides) -> dict:
    defaults = {
        "advertiser_name": "Acme",
        "iab_category": "IAB-9",
        "total_budget_cents": 100000,
        "daily_budget_cents": 100000,
        "cpm_cents": 500,
        "flight_start_date": C.FLIGHT_START,
        "flight_end_date": C.FLIGHT_END,
    }
    defaults.update(overrides)
    return defaults


def create_ad_creative_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "brand": "Acme Soda",
        "iab_category": "IAB-9",
        "duration_seconds": 30,
    }
    defaults.update(overrides)
    return defaults


def create_house_ad_payload(**overrides) -> dict:
    defaults = {
        "name": "House Promo",
        "priority_weight": 5,
        "daily_impression_cap": 5,
    }
    defaults.update(overrides)
    return defaults


def create_distributor_platform_payload(**overrides) -> dict:
    defaults = {
        "name": "Roku-like",
        "reporting_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_distribution_agreement_payload(channel_id, platform_id, **overrides) -> dict:
    defaults = {
        "channel_id": channel_id,
        "platform_id": platform_id,
        "rev_share_bps_below": 3000,
        "rev_share_bps_above": 4000,
        "tier_threshold_cents": 100000,
        "minimum_guarantee_cents": 0,
        "effective_start_date": C.AGREEMENT_START,
        "effective_end_date": C.AGREEMENT_END,
    }
    defaults.update(overrides)
    return defaults


def create_revenue_report_payload(channel_id, platform_id, **overrides) -> dict:
    defaults = {
        "channel_id": channel_id,
        "platform_id": platform_id,
        "period_month": C.PERIOD_MONTH,
    }
    defaults.update(overrides)
    return defaults


def create_viewership_event_payload(channel_id, event_type, **overrides) -> dict:
    defaults = {
        "channel_id": channel_id,
        "event_type": event_type,
        "viewer_session_id": "s1",
        "occurred_at_utc": "2026-09-01T00:07:30Z",
    }
    defaults.update(overrides)
    return defaults
