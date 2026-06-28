"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must be >= 1, got {data['version']}"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must NOT carry a version field"
    assert "updated_at" not in data, "append-only entity must NOT carry an updated_at field"


def assert_brand(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["available_budget_cents"], int)
    assert data["available_budget_cents"] == data["budget_cents"] - data["committed_cents"], \
        "available_budget_cents must equal budget_cents - committed_cents"


def assert_creator(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["handle"], str) and len(data["handle"]) > 0
    assert data["primary_platform"] in ("INSTAGRAM", "TIKTOK", "YOUTUBE")
    assert data["payout_method"] in ("ACH", "PAYPAL")
    assert isinstance(data["tax_id_on_file"], bool)
    assert data["discovery_status"] in ("NEW", "DISCOVERABLE", "SUPPRESSED")
    assert data["brand_safety_status"] in ("CLEAR", "FLAGGED", "BLOCKED")
    assert isinstance(data["ytd_paid_cents"], int)


def assert_campaign(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["status"] in ("DRAFT", "OPEN", "ACTIVE", "CLOSED", "CANCELLED")
    assert isinstance(data["campaign_budget_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["actual_spend_cents"], int)
    assert isinstance(data["requires_ftc_disclosure"], bool)


def assert_deliverable(data: dict):
    _assert_common_versioned(data)
    assert data["content_type"] in ("FEED_POST", "STORY", "REEL", "VIDEO")
    assert data["quantity"] >= 1
    assert data["base_rate_cents"] >= 0


def assert_offer(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("OFFERED", "COUNTERED", "ACCEPTED", "DECLINED", "EXPIRED")
    assert data["last_actor"] in ("BRAND", "CREATOR")
    assert data["initiated_by"] in ("BRAND", "CREATOR")
    assert data["current_amount_cents"] >= 1
    assert data["round_count"] >= 0
    assert data["exclusivity_days"] >= 0


def assert_contract(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("ACTIVE", "FULFILLED", "SETTLED", "CANCELLED")
    assert data["contracted_rate_cents"] >= 1
    assert is_iso8601_timestamp(data["exclusivity_start"])
    assert is_iso8601_timestamp(data["exclusivity_end"])


def assert_content_submission(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("SUBMITTED", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED")
    assert isinstance(data["media_url"], str) and len(data["media_url"]) > 0
    assert isinstance(data["has_ftc_disclosure"], bool)
    assert data["revision_count"] >= 0


def assert_attribution_asset(data: dict):
    _assert_common_versioned(data)
    assert data["asset_type"] in ("TRACKING_LINK", "PROMO_CODE")
    assert isinstance(data["code_or_slug"], str) and len(data["code_or_slug"]) > 0
    assert data["status"] in ("ENABLED", "DISABLED")


def assert_payout(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("PENDING", "RELEASED", "SETTLED", "FAILED")
    assert data["gross_amount_cents"] >= 1
    assert data["platform_fee_cents"] >= 0
    assert data["tax_withholding_cents"] >= 0
    assert data["net_amount_cents"] >= 0
    assert data["net_amount_cents"] == (
        data["gross_amount_cents"] - data["platform_fee_cents"] - data["tax_withholding_cents"]
    ), "net must equal gross - platform_fee - tax_withholding"


def assert_tax_form_1099(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("GENERATED", "FILED", "VOIDED")
    assert isinstance(data["tax_year"], int)
    assert data["total_reported_cents"] >= 0


def assert_brand_safety_flag(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("OPEN", "RESOLVED")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["reason_code"] in ("HATE_SPEECH", "FRAUD_SIGNAL", "NSFW", "MISINFORMATION", "OTHER")


def assert_audience_snapshot(data: dict):
    _assert_append_only(data)
    assert isinstance(data["fraud_score"], (int, float))
    assert 0 <= data["fraud_score"] <= 100


def assert_conversion_event(data: dict):
    _assert_append_only(data)
    assert data["event_type"] in ("IMPRESSION", "ENGAGEMENT", "SALE")
    assert data["count"] >= 1
    assert data["revenue_cents"] >= 0
