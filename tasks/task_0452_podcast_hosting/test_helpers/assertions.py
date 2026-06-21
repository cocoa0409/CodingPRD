"""Entity assertions and domain invariant checkers (Podcast Hosting & Monetization API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common-field helpers ─────────────────────────────────────────────────────
def _assert_common_versioned(data: dict):
    """id + created_at + updated_at + version (common_fields: true)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


# ─── Per-entity assertions ────────────────────────────────────────────────────
def assert_publisher(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["payout_email"], str)
    assert isinstance(data["revenue_share_pct"], (int, float))
    assert 0.0 <= data["revenue_share_pct"] <= 1.0


def assert_advertiser(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["billing_email"], str)


def assert_listener(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["display_name"], str)


def assert_show(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["publisher_id"], str)
    assert isinstance(data["title"], str)
    assert data["category"] in ["TECH", "NEWS", "COMEDY", "BUSINESS", "EDUCATION", "TRUE_CRIME"]
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "ARCHIVED"]
    assert isinstance(data["monetization_enabled"], bool)
    assert isinstance(data["episode_count"], int)


def assert_episode(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["show_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["duration_ms"], int)
    assert isinstance(data["total_ad_slots"], int)
    assert isinstance(data["offered_positions"], list)
    assert data["media_status"] in ["NONE", "PENDING", "PROCESSING", "READY", "FAILED"]
    assert data["publish_status"] in ["DRAFT", "SCHEDULED", "PUBLISHED", "UNPUBLISHED", "DELETED"]
    assert isinstance(data["filled_slots"], int)
    assert isinstance(data["available_slots"], int)
    assert isinstance(data["fill_rate"], (int, float))


def assert_media_asset(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["episode_id"], str)
    assert isinstance(data["source_filename"], str)
    assert isinstance(data["source_duration_ms"], int)
    assert data["status"] in ["UPLOADED", "TRANSCODING", "READY", "FAILED"]
    assert isinstance(data["transcode_attempts"], int)
    assert isinstance(data["output_duration_ms"], int)


def assert_feed(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["show_id"], str)
    assert data["visibility"] in ["PUBLIC", "PRIVATE"]
    assert data["status"] in ["ENABLED", "DISABLED"]
    assert isinstance(data["token_required"], bool)


def assert_subscription(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["listener_id"], str)
    assert isinstance(data["show_id"], str)
    assert isinstance(data["price_cents"], int)
    assert data["status"] in ["PENDING", "ACTIVE", "PAST_DUE", "CANCELLED"]


def assert_distribution(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["show_id"], str)
    assert data["channel"] in ["APPLE", "SPOTIFY"]
    assert data["status"] in ["PENDING", "LIVE", "REJECTED", "REMOVED"]


def assert_ad_campaign(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["advertiser_id"], str)
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["bid_cpm_cents"], int)
    assert data["targeting_category"] in ["TECH", "NEWS", "COMEDY", "BUSINESS", "EDUCATION", "TRUE_CRIME"]
    assert isinstance(data["premium_targeting"], bool)
    assert data["status"] in ["DRAFT", "ACTIVE", "PAUSED", "EXHAUSTED", "COMPLETED"]
    assert isinstance(data["reserved_budget_cents"], int)
    assert isinstance(data["spent_budget_cents"], int)
    assert isinstance(data["available_budget_cents"], int)


def assert_ad_placement(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["episode_id"], str)
    assert data["position"] in ["PRE_ROLL", "MID_ROLL", "POST_ROLL"]
    assert isinstance(data["ad_duration_ms"], int)
    assert isinstance(data["forecast_impressions"], int)
    assert isinstance(data["delivered_impressions"], int)
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["final_cost_cents"], int)
    assert data["status"] in ["PROPOSED", "INSERTED", "DELIVERED", "CANCELLED", "REJECTED"]


def assert_payout_statement(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["publisher_id"], str)
    assert data["status"] in ["DRAFT", "FINALIZED", "PAID", "VOID"]
    assert isinstance(data["gross_revenue_cents"], int)
    assert isinstance(data["platform_fee_cents"], int)
    assert isinstance(data["net_payable_cents"], int)
    assert isinstance(data["settled_revenue_cents"], int)


def assert_download_event(data: dict):
    """Append-only record (common_fields: false) — carries ONLY id + created_at as
    system fields; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["episode_id"], str)
    assert isinstance(data["counted"], bool)


# ─── Domain invariant checkers ────────────────────────────────────────────────
def assert_campaign_budget_invariant(data: dict):
    """PRD §3.4: budget_cents always equals available + reserved + spent."""
    assert (
        data["budget_cents"]
        == data["available_budget_cents"] + data["reserved_budget_cents"] + data["spent_budget_cents"]
    ), "budget invariant: budget == available + reserved + spent must hold"


def assert_episode_slot_invariant(data: dict):
    """PRD §3.2: available_slots == total_ad_slots - filled_slots."""
    assert data["available_slots"] == data["total_ad_slots"] - data["filled_slots"], (
        "slot invariant: available_slots == total_ad_slots - filled_slots must hold"
    )


def assert_payout_residual_invariant(data: dict):
    """PRD §3.8: gross equals net plus platform fee."""
    assert (
        data["gross_revenue_cents"] == data["net_payable_cents"] + data["platform_fee_cents"]
    ), "payout invariant: gross == net + platform_fee must hold"
