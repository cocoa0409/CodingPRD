"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import IMAGE_WEIGHT


def _assert_common_fields(data: dict, entity: str):
    """id / created_at / updated_at / version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_two_decimal_places(value, label="score"):
    assert value is not None, f"{label} must be present"
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{label} must be carried to exactly 2 decimal places, got {value}"
    )


def assert_retailer(data: dict):
    _assert_common_fields(data, "Retailer")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["retailer_code"], str) and 3 <= len(data["retailer_code"]) <= 8
    assert data["status"] in ("ACTIVE", "PAUSED", "OFFBOARDED")
    assert isinstance(data["min_image_count"], int) and data["min_image_count"] >= 0
    assert isinstance(data["feed_slot_capacity"], int) and data["feed_slot_capacity"] >= 1
    assert (
        isinstance(data["max_concurrent_feed_windows"], int)
        and data["max_concurrent_feed_windows"] >= 1
    )
    assert isinstance(data["enhanced_content_requires_approval"], bool)
    assert isinstance(data["feed_slots_reserved"], int)
    assert 0 <= data["feed_slots_reserved"] <= data["feed_slot_capacity"], (
        "feed_slots_reserved must stay between 0 and feed_slot_capacity inclusive"
    )


def assert_attribute_definition(data: dict):
    _assert_common_fields(data, "AttributeDefinition")
    assert isinstance(data["attribute_key"], str) and 2 <= len(data["attribute_key"]) <= 40
    assert data["data_type"] in ("STRING", "INTEGER", "DECIMAL", "ENUM")
    assert data["taxonomy_group"] in ("CORE", "MARKETING", "VARIANT", "COMPLIANCE")
    assert isinstance(data["max_chars"], int) and data["max_chars"] >= 1
    assert float(data["base_weight"]) > 0
    assert isinstance(data["is_global_required"], bool)


def assert_retailer_requirement(data: dict):
    _assert_common_fields(data, "RetailerRequirement")
    assert is_valid_uuid(data["retailer_id"])
    assert isinstance(data["attribute_key"], str)
    assert data["requirement_level"] in ("REQUIRED", "RECOMMENDED", "OPTIONAL")


def assert_product(data: dict):
    _assert_common_fields(data, "Product")
    assert isinstance(data["sku"], str) and 3 <= len(data["sku"]) <= 40
    assert isinstance(data["gtin"], str) and 8 <= len(data["gtin"]) <= 14
    assert data["status"] in ("DRAFT", "ACTIVE")
    assert 0.00 <= float(data["shelf_health_index"]) <= 100.00
    assert isinstance(data["open_alert_count"], int) and data["open_alert_count"] >= 0
    assert data["governance_flag"] in ("NONE", "CONTENT_AT_RISK", "LISTING_RISK")
    assert_two_decimal_places(data["shelf_health_index"], "shelf_health_index")
    assert_two_decimal_places(data["conversion_lift_pct"], "conversion_lift_pct")


def assert_content_version(data: dict):
    _assert_common_fields(data, "ContentVersion")
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert data["state"] in ("DRAFT", "IN_REVIEW", "PINNED", "SUPERSEDED")
    assert isinstance(data["image_count"], int) and data["image_count"] >= 0
    assert isinstance(data["pin_count"], int) and data["pin_count"] >= 0
    assert isinstance(data["author_user_id"], str) and data["author_user_id"]


def assert_content_attribute_value(data: dict):
    _assert_common_fields(data, "ContentAttributeValue")
    assert is_valid_uuid(data["content_version_id"])
    assert isinstance(data["value"], str) and 1 <= len(data["value"]) <= 2000
    assert isinstance(data["char_count"], int)
    assert data["char_count"] == len(data["value"].strip()), (
        "char_count is the length of value after leading and trailing whitespace is stripped"
    )
    assert isinstance(data["type_valid"], bool)


def assert_media_asset(data: dict):
    _assert_common_fields(data, "MediaAsset")
    assert is_valid_uuid(data["product_id"])
    assert data["asset_role"] in ("HERO_IMAGE", "SECONDARY_IMAGE", "VIDEO", "A_PLUS_MODULE")
    assert isinstance(data["source_uri"], str) and 1 <= len(data["source_uri"]) <= 500
    assert data["approval_state"] in ("PENDING", "APPROVED", "REJECTED")


def assert_retailer_listing(data: dict):
    _assert_common_fields(data, "RetailerListing")
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["retailer_id"])
    assert data["syndication_state"] in ("NOT_SYNDICATED", "PENDING", "LIVE", "ERROR_HOLD")
    assert data["shelf_state"] in ("OK", "OOS_WATCH", "UNAUTHORIZED", "SUSPENDED")
    for field in (
        "completeness_score_declared",
        "completeness_score_certified",
        "readiness_score",
    ):
        assert 0.00 <= float(data[field]) <= 100.00, f"{field} must be clamped to 0..100"
        assert_two_decimal_places(data[field], field)
    assert isinstance(data["in_stock"], bool)
    assert isinstance(data["open_blocking_error_count"], int)


def assert_syndication_job(data: dict):
    _assert_common_fields(data, "SyndicationJob")
    assert is_valid_uuid(data["retailer_listing_id"])
    assert is_valid_uuid(data["content_version_id"])
    assert isinstance(data["slot_count"], int) and 1 <= data["slot_count"] <= 10
    assert data["state"] in (
        "QUEUED",
        "TRANSMITTED",
        "ACCEPTED",
        "PARTIALLY_ACCEPTED",
        "REJECTED",
        "INVALIDATED",
        "CANCELLED",
    )
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert isinstance(data["service_fee_cents"], int), (
        "service_fee_cents is an integer number of cents and is never fractional"
    )
    assert_two_decimal_places(data["readiness_at_queue"], "readiness_at_queue")


def assert_rejection_error(data: dict):
    _assert_common_fields(data, "RejectionError")
    assert is_valid_uuid(data["syndication_job_id"])
    assert isinstance(data["retailer_error_code"], str) and 1 <= len(data["retailer_error_code"]) <= 40
    assert data["severity"] in ("BLOCKING", "WARNING")
    assert isinstance(data["message"], str) and 1 <= len(data["message"]) <= 500
    assert data["state"] in ("OPEN", "RESOLVED", "WAIVED")


def assert_change_request(data: dict):
    _assert_common_fields(data, "ChangeRequest")
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["retailer_id"])
    assert is_valid_uuid(data["target_content_version_id"])
    assert isinstance(data["rationale"], str) and 1 <= len(data["rationale"]) <= 500
    assert data["state"] in ("DRAFT", "IN_REVIEW", "APPROVED", "REJECTED")
    assert data["legal_review_state"] in ("PENDING", "APPROVED", "REJECTED")
    assert data["brand_review_state"] in ("PENDING", "APPROVED", "REJECTED")
    assert isinstance(data["author_user_id"], str) and data["author_user_id"]


def assert_enhanced_deployment(data: dict):
    _assert_common_fields(data, "EnhancedContentDeployment")
    assert is_valid_uuid(data["retailer_listing_id"])
    assert is_valid_uuid(data["change_request_id"])
    assert is_valid_uuid(data["media_asset_id"])
    assert data["module_kind"] in ("A_PLUS_PAGE", "COMPARISON_CHART", "VIDEO_BLOCK")
    assert data["state"] in ("PENDING_RETAILER_APPROVAL", "LIVE", "REJECTED", "WITHDRAWN")
    assert data["window_end"] > data["window_start"]


def assert_shelf_observation(data: dict):
    """PRD §2.4: an append-only event row carrying only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "ShelfObservation.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "ShelfObservation.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "ShelfObservation has no updated_at"
    assert "version" not in data, "ShelfObservation has no version"
    assert isinstance(data["in_stock"], bool)
    assert 0.00 <= float(data["content_accuracy_pct"]) <= 100.00
    assert 0.00 <= float(data["rating_avg"]) <= 5.00
    assert isinstance(data["rating_count"], int) and data["rating_count"] >= 0
    assert isinstance(data["unauthorized_seller_count"], int)
    assert 0.00 <= float(data["conversion_rate_pct"]) <= 100.00
    assert isinstance(data["units_sold"], int) and data["units_sold"] >= 0


def assert_shelf_alert(data: dict):
    _assert_common_fields(data, "ShelfAlert")
    assert is_valid_uuid(data["retailer_listing_id"])
    assert data["alert_type"] in (
        "OUT_OF_STOCK",
        "UNAUTHORIZED_LISTING",
        "CONTENT_DRIFT",
        "HEALTH_DEGRADED",
    )
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["state"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED")


def assert_completeness_diagnostic(data: dict):
    """PRD §3.4 diagnostic read shape."""
    assert is_valid_uuid(data["retailer_listing_id"])
    for field in ("declared_score", "certified_score"):
        assert 0.00 <= float(data[field]) <= 100.00
        assert_two_decimal_places(data[field], field)
    assert float(data["requirement_weight_total"]) >= IMAGE_WEIGHT or float(
        data["requirement_weight_total"]
    ) == 0.0
    assert isinstance(data["missing_required_keys"], list)
    assert isinstance(data["over_limit_keys"], list)
    assert data["missing_required_keys"] == sorted(data["missing_required_keys"]), (
        "missing_required_keys is sorted in ascending alphabetical order of attribute key"
    )
    assert data["over_limit_keys"] == sorted(data["over_limit_keys"]), (
        "over_limit_keys is sorted in ascending alphabetical order of attribute key"
    )


def assert_shelf_summary(data: dict):
    """PRD §3.9 computed read shape."""
    assert is_valid_uuid(data["product_id"])
    assert 0.00 <= float(data["shelf_health_index"]) <= 100.00
    assert_two_decimal_places(data["shelf_health_index"], "shelf_health_index")
    assert isinstance(data["qualifying_listing_count"], int)
    assert isinstance(data["retailer_subscores"], list)
    assert len(data["retailer_subscores"]) == data["qualifying_listing_count"]
    assert data["lift_variant"] in ("post_pin_window", "quality_split")
    assert isinstance(data["high_group_size"], int)
    assert isinstance(data["base_group_size"], int)


def assert_slot_ledger(retailer: dict, expected_reserved: int):
    """PRD §2.9: feed_slots_reserved is recomputed from its source rows."""
    assert retailer["feed_slots_reserved"] == expected_reserved, (
        f"feed_slots_reserved should be {expected_reserved}, "
        f"got {retailer['feed_slots_reserved']}"
    )
    assert 0 <= retailer["feed_slots_reserved"] <= retailer["feed_slot_capacity"]


def assert_pin_ledger(content_version: dict, expected_pin_count: int):
    """PRD §2.9: pin_count counts listing pins plus live deployment references."""
    assert content_version["pin_count"] == expected_pin_count, (
        f"pin_count should be {expected_pin_count}, got {content_version['pin_count']}"
    )
