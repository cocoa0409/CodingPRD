"""Payload factories — one per entity, input fields only (wire service PRD).

Codes and slugs default to uuid-derived unique values so that a test creating
several resources of the same kind never trips the uniqueness rules.
"""
import uuid

DEFAULTS = {
    "PACKAGE_BASE_FEE_CENTS": 10_000,
    "PACKAGE_MEDIA_RIGHTS": "TEXT_PHOTO_VIDEO",
    "TIER_MIN_AUDIENCE": 1,
    "TIER_MAX_AUDIENCE": 10_000,
    "TIER_MULTIPLIER_BP": 10_000,
    "TIER_QUOTA": 5,
    "TIER_OVERAGE_CENTS": 100,
    "TIER_MEMBER_DISCOUNT_PCT": 0,
    "FEED_TOPIC": "NATIONAL",
    "FEED_EMBARGO_WINDOW_MINUTES": 0,
    "SUBSCRIBER_AUDIENCE": 5_000,
    "ARTICLE_WORD_COUNT": 100,
    "SUBSCRIPTION_START_AT": "2026-05-10T00:00:00Z",
    "INVOICE_BILLING_MONTH": "2026-05",
}


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_package_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("PKG"),
        "display_name": "Test Package",
        "media_rights": DEFAULTS["PACKAGE_MEDIA_RIGHTS"],
        "base_monthly_fee_cents": DEFAULTS["PACKAGE_BASE_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_tier_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("TIER"),
        "min_audience": DEFAULTS["TIER_MIN_AUDIENCE"],
        "max_audience": DEFAULTS["TIER_MAX_AUDIENCE"],
        "circulation_multiplier_basis_points": DEFAULTS["TIER_MULTIPLIER_BP"],
        "monthly_republish_quota": DEFAULTS["TIER_QUOTA"],
        "overage_per_article_cents": DEFAULTS["TIER_OVERAGE_CENTS"],
        "member_discount_pct": DEFAULTS["TIER_MEMBER_DISCOUNT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_feed_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("FEED"),
        "topic": DEFAULTS["FEED_TOPIC"],
        "embargo_window_minutes": DEFAULTS["FEED_EMBARGO_WINDOW_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_subscriber_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _uniq("Pub"),
        "billing_email": f"{uuid.uuid4().hex[:8]}@example.com",
        "declared_audience": DEFAULTS["SUBSCRIBER_AUDIENCE"],
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(package_id: str, start_at: str = None, **overrides) -> dict:
    defaults = {
        "package_id": package_id,
        "start_at": start_at or DEFAULTS["SUBSCRIPTION_START_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_entitlement_payload(feed_id: str, **overrides) -> dict:
    defaults = {"feed_id": feed_id}
    defaults.update(overrides)
    return defaults


def create_article_payload(feed_id: str, **overrides) -> dict:
    defaults = {
        "feed_id": feed_id,
        "headline": "Test Headline",
        "body_word_count": DEFAULTS["ARTICLE_WORD_COUNT"],
        "slug": _uniq("slug"),
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(kind: str = "PHOTO", rights_scope: str = "WIRE", **overrides) -> dict:
    defaults = {
        "kind": kind,
        "rights_scope": rights_scope,
        "file_ref": _uniq("file"),
    }
    defaults.update(overrides)
    return defaults


def create_publication_payload(subscription_id: str, article_id: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "article_id": article_id,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(billing_month: str = None, **overrides) -> dict:
    defaults = {"billing_month": billing_month or DEFAULTS["INVOICE_BILLING_MONTH"]}
    defaults.update(overrides)
    return defaults
