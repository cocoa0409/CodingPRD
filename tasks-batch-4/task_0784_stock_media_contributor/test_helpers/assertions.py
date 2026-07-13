"""Entity assertions and domain invariant checkers (PRD-derived)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_contributor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "contributor id must be a UUID"
    assert data["onboarding_status"] in ("PENDING", "ACTIVE", "SUSPENDED")
    assert data["tax_form_status"] in ("MISSING", "SUBMITTED", "VERIFIED", "REJECTED")
    assert data["exclusivity"] in ("NON_EXCLUSIVE", "EXCLUSIVE")
    assert data["royalty_level"] in ("BRONZE", "SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["lifetime_earnings_cents"], int)
    assert data["lifetime_earnings_cents"] >= 0, "lifetime_earnings_cents is never negative"
    assert isinstance(data["available_balance_cents"], int)
    assert isinstance(data["accepted_asset_count"], int)
    assert data["accepted_asset_count"] >= 0
    assert isinstance(data["strike_count"], int)
    assert data["strike_count"] >= 0
    assert isinstance(data["version"], int)


def assert_asset(data: dict):
    assert is_valid_uuid(data.get("id", "")), "asset id must be a UUID"
    assert data["status"] in ("DRAFT", "SUBMITTED", "IN_REVIEW", "ACCEPTED", "REJECTED", "TAKEN_DOWN")
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["media_type"] in ("PHOTO", "VIDEO", "VECTOR")
    assert data["content_category"] in ("COMMERCIAL", "EDITORIAL")
    assert isinstance(data["keywords"], list) and len(data["keywords"]) >= 1


def assert_download(data: dict):
    assert is_valid_uuid(data.get("id", "")), "download id must be a UUID"
    assert data["earning_status"] in ("PENDING", "AVAILABLE", "REVERSED")
    assert isinstance(data["sale_price_cents"], int)
    assert isinstance(data["royalty_amount_cents"], int)
    assert is_iso8601_timestamp(data.get("available_at", "")), "available_at must be ISO 8601"


def assert_payout(data: dict):
    assert is_valid_uuid(data.get("id", "")), "payout id must be a UUID"
    assert data["status"] in ("REQUESTED", "PROCESSING", "PAID", "FAILED")
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["withholding_cents"], int)
    assert isinstance(data["net_amount_cents"], int)
    assert data["net_amount_cents"] == data["gross_amount_cents"] - data["withholding_cents"], \
        "net_amount_cents must equal gross minus withholding"


def assert_review_is_immutable_shape(data: dict):
    """AssetReview is the sole common-fields exception: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "review id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "AssetReview must not carry a version field"
    assert "updated_at" not in data, "AssetReview must not carry an updated_at field"
