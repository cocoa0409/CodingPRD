"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

from .constants import (
    DEFAULT_MEASUREMENT_WINDOW_DAYS,
    DEFAULT_SLOT_CAPACITY,
    FLIGHT_END,
    FLIGHT_START,
    TEST_DEFAULTS,
)


def create_show_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Show",
        "content_category": "NEWS",
        "avg_downloads_30d": TEST_DEFAULTS["AVG_DOWNLOADS_30D"],
    }
    defaults.update(overrides)
    return defaults


def create_episode_payload(show_id, **overrides) -> dict:
    defaults = {
        "show_id": show_id,
        "title": "Test Episode",
        "publish_at": FLIGHT_START,
    }
    defaults.update(overrides)
    return defaults


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Agency",
        "commission_bps": TEST_DEFAULTS["COMMISSION_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_advertiser_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Advertiser",
        "category": "FINTECH",
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(advertiser_id, **overrides) -> dict:
    defaults = {
        "advertiser_id": advertiser_id,
        "name": "Test Campaign",
        "flight_start": FLIGHT_START,
        "flight_end": FLIGHT_END,
        "booked_impressions": TEST_DEFAULTS["BOOKED_IMPRESSIONS"],
        "cpm_cents": TEST_DEFAULTS["CPM_CENTS"],
        "billing_model": "ACTUAL_DELIVERY",
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(campaign_id, ad_copy_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "ad_format": "PRODUCED_SPOT",
        "position": "MID_ROLL",
        "reserved_impressions": TEST_DEFAULTS["RESERVED_IMPRESSIONS"],
        "priority": TEST_DEFAULTS["PRIORITY"],
        "ad_copy_id": ad_copy_id,
    }
    defaults.update(overrides)
    return defaults


def create_ad_copy_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "kind": "PRODUCED_AUDIO",
        "script_text": "Test spot copy",
    }
    defaults.update(overrides)
    return defaults


def create_downloads_payload(episode_id, **overrides) -> dict:
    defaults = {
        "episode_id": episode_id,
        "listener_key_prefix": "L",
        "count": 1,
        "occurred_at": "2026-08-05T00:00:00Z",
        "user_agent_class": "HUMAN",
    }
    defaults.update(overrides)
    return defaults


def create_attribution_event_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "kind": "PIXEL",
        "occurred_at": "2026-08-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(campaign_id, **overrides) -> dict:
    defaults = {"campaign_id": campaign_id}
    defaults.update(overrides)
    return defaults
