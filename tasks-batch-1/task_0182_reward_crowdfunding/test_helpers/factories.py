"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CREATOR_NAME": "Test Creator",
    "PAYOUT_CURRENCY": "USD",
    "BACKER_EMAIL": "backer@example.com",
    "BACKER_NAME": "Test Backer",
    "CAMPAIGN_TITLE": "Test Campaign",
    "FUNDING_GOAL_CENTS": 100000,
    "FUNDING_MODEL": "FLEXIBLE",
    "DEADLINE_UTC": "2026-07-01T00:00:00.000Z",
    "TIER_TITLE": "Test Tier",
    "TIER_PRICE_CENTS": 5000,
    "TIER_WEIGHT_GRAMS": 800,
    "STRETCH_TITLE": "Test Stretch Goal",
    "ADDON_TITLE": "Test AddOn",
    "ADDON_PRICE_CENTS": 2000,
    "ADDON_WEIGHT_GRAMS": 300,
    "PLEDGE_AMOUNT_CENTS": 5000,
    "DESTINATION_ZONE": "DOMESTIC",
    "SHIPPING_ADDRESS": "1 Main St",
}


def create_creator_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["CREATOR_NAME"],
        "payout_currency": DEFAULTS["PAYOUT_CURRENCY"],
    }
    defaults.update(overrides)
    return defaults


def create_backer_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["BACKER_EMAIL"],
        "display_name": DEFAULTS["BACKER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(creator_id, **overrides) -> dict:
    defaults = {
        "creator_id": creator_id,
        "title": DEFAULTS["CAMPAIGN_TITLE"],
        "funding_goal_cents": DEFAULTS["FUNDING_GOAL_CENTS"],
        "funding_model": DEFAULTS["FUNDING_MODEL"],
        "deadline_utc": DEFAULTS["DEADLINE_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_tier_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["TIER_TITLE"],
        "price_cents": DEFAULTS["TIER_PRICE_CENTS"],
        "weight_grams": DEFAULTS["TIER_WEIGHT_GRAMS"],
    }
    defaults.update(overrides)
    return defaults


def create_stretch_goal_payload(threshold_cents, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["STRETCH_TITLE"],
        "threshold_cents": threshold_cents,
    }
    defaults.update(overrides)
    return defaults


def create_addon_product_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["ADDON_TITLE"],
        "price_cents": DEFAULTS["ADDON_PRICE_CENTS"],
        "weight_grams": DEFAULTS["ADDON_WEIGHT_GRAMS"],
    }
    defaults.update(overrides)
    return defaults


def create_pledge_payload(backer_id, tier_id, expected_campaign_version, **overrides) -> dict:
    defaults = {
        "backer_id": backer_id,
        "tier_id": tier_id,
        "pledge_amount_cents": DEFAULTS["PLEDGE_AMOUNT_CENTS"],
        "destination_zone": DEFAULTS["DESTINATION_ZONE"],
        "expected_campaign_version": expected_campaign_version,
    }
    defaults.update(overrides)
    return defaults


def attach_addon_payload(addon_id, quantity, **overrides) -> dict:
    defaults = {
        "addon_id": addon_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def authorization_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def survey_payload(**overrides) -> dict:
    defaults = {"shipping_address": DEFAULTS["SHIPPING_ADDRESS"]}
    defaults.update(overrides)
    return defaults


def clock_payload(now_utc, **overrides) -> dict:
    defaults = {"now_utc": now_utc}
    defaults.update(overrides)
    return defaults
