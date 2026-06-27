"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "BRAND_LEGAL_NAME": "Test Brand",
    "BRAND_EMAIL": "ops@test.com",
    "BRAND_BUDGET": 1_000_000,
    "CREATOR_HANDLE": "@test_creator",
    "PLATFORM": "INSTAGRAM",
    "CAMPAIGN_TITLE": "Test Campaign",
    "CAMPAIGN_BUDGET": 200_000,
    "STARTS_AT": "2026-02-01T00:00:00Z",
    "ENDS_AT": "2026-03-01T00:00:00Z",
    "CONTENT_TYPE": "FEED_POST",
    "DUE_AT": "2026-02-20T00:00:00Z",
    "BASE_RATE": 60_000,
    "OFFER_AMOUNT": 60_000,
    "MEDIA_URL": "https://example.com/content",
    "CAPTION": "Loving this #ad",
    "FOLLOWERS": 50_000,
    "ENGAGEMENT_RATE": 0.05,
    "ESTIMATED_REACH": 25_000,
    "FAKE_FOLLOWER_PCT": 0.05,
}


def create_brand_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["BRAND_LEGAL_NAME"],
        "contact_email": DEFAULTS["BRAND_EMAIL"],
        "budget_cents": DEFAULTS["BRAND_BUDGET"],
    }
    defaults.update(overrides)
    return defaults


def create_creator_payload(**overrides) -> dict:
    defaults = {
        "handle": DEFAULTS["CREATOR_HANDLE"],
        "primary_platform": DEFAULTS["PLATFORM"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(brand_id, **overrides) -> dict:
    defaults = {
        "brand_id": brand_id,
        "title": DEFAULTS["CAMPAIGN_TITLE"],
        "campaign_budget_cents": DEFAULTS["CAMPAIGN_BUDGET"],
        "starts_at": DEFAULTS["STARTS_AT"],
        "ends_at": DEFAULTS["ENDS_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_deliverable_payload(**overrides) -> dict:
    defaults = {
        "content_type": DEFAULTS["CONTENT_TYPE"],
        "quantity": 1,
        "due_at": DEFAULTS["DUE_AT"],
        "base_rate_cents": DEFAULTS["BASE_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(campaign_id, creator_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "creator_id": creator_id,
        "current_amount_cents": DEFAULTS["OFFER_AMOUNT"],
        "exclusivity_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_content_submission_payload(deliverable_id, contract_id, **overrides) -> dict:
    defaults = {
        "deliverable_id": deliverable_id,
        "contract_id": contract_id,
        "media_url": DEFAULTS["MEDIA_URL"],
        "caption": DEFAULTS["CAPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_attribution_asset_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "asset_type": "TRACKING_LINK",
        "code_or_slug": "test-slug",
    }
    defaults.update(overrides)
    return defaults


def create_conversion_payload(**overrides) -> dict:
    defaults = {
        "event_type": "IMPRESSION",
        "count": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_audience_snapshot_payload(**overrides) -> dict:
    defaults = {
        "follower_count": DEFAULTS["FOLLOWERS"],
        "avg_engagement_rate": DEFAULTS["ENGAGEMENT_RATE"],
        "estimated_reach": DEFAULTS["ESTIMATED_REACH"],
        "fake_follower_pct": DEFAULTS["FAKE_FOLLOWER_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_brand_safety_flag_payload(**overrides) -> dict:
    defaults = {
        "severity": "HIGH",
        "reason_code": "FRAUD_SIGNAL",
    }
    defaults.update(overrides)
    return defaults
