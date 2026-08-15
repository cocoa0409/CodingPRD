"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """Append-only records carry only id and created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_agent(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["email"], str) and data["email"]


def assert_listing(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert isinstance(data["address_line1"], str) and data["address_line1"]
    assert isinstance(data["city"], str) and data["city"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["postal_code"], str) and data["postal_code"]
    assert data["property_type"] in (
        "SINGLE_FAMILY", "CONDO", "TOWNHOUSE", "MULTI_FAMILY", "LAND"
    )
    assert isinstance(data["list_price_cents"], int)
    assert data["lifecycle_status"] in (
        "DRAFT", "PENDING_REVIEW", "COMPLIANCE_HOLD", "ACTIVE",
        "UNDER_CONTRACT", "SOLD", "WITHDRAWN", "EXPIRED",
    )
    assert data["syndication_posture"] in (
        "NOT_SYNDICATED", "SYNDICATING", "SYNDICATED", "DEGRADED", "SUSPENDED"
    )
    assert isinstance(data["relist_count"], int) and data["relist_count"] >= 0
    assert isinstance(data["audited_breach_count"], int)
    assert isinstance(data["provisional_breach_count"], int)
    raw = data.get("feedback_score_raw")
    assert raw is None or isinstance(raw, (int, float)), "raw score null or numeric"
    weighted = data.get("feedback_score_weighted")
    assert weighted is None or isinstance(weighted, (int, float)), "weighted score null or numeric"


def assert_media_asset(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert data["kind"] in ("PHOTO", "VIDEO", "FLOOR_PLAN")
    assert isinstance(data["file_url"], str) and data["file_url"]
    assert isinstance(data["file_bytes"], int) and data["file_bytes"] > 0
    assert isinstance(data["is_primary"], bool)
    assert data["status"] in ("UPLOADED", "READY", "REJECTED", "ARCHIVED")


def assert_compliance_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_portal_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["portal_name"], str) and data["portal_name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["sla_seconds"], int) and data["sla_seconds"] > 0
    assert isinstance(data["discount_pct"], (int, float))
    assert data["rounding_increment_cents"] in (10000, 50000, 100000, 1000000)


def assert_blackout_window(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("portal_account_id", "")), "portal_account_id must be a UUID"
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"


def assert_feed_subscription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert is_valid_uuid(data.get("portal_account_id", "")), "portal_account_id must be a UUID"
    assert data["status"] in ("SUBSCRIBED", "PAUSED", "COMPLETED")


def assert_syndication_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("feed_subscription_id", "")), "feed_subscription_id must be a UUID"
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert data["job_type"] in (
        "FULL_SYNC", "PRICE_UPDATE", "REMARKS_UPDATE",
        "STATUS_UPDATE", "MEDIA_UPDATE", "TERMINAL_SYNC",
    )
    assert data["status"] in (
        "QUEUED", "DISPATCHED", "ACKED", "FAILED",
        "RETRY_QUEUED", "SUPERSEDED", "CANCELLED", "DEAD_LETTER",
    )
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert is_iso8601_timestamp(data.get("scheduled_at", "")), "scheduled_at must be ISO 8601"


def assert_listing_event(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert data["event_type"] in ("PRICE_CHANGE", "REMARKS_UPDATE", "STATUS_CHANGE")


def assert_showing_window(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_showing_feedback(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("showing_window_id", "")), "showing_window_id must be a UUID"
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    assert data["status"] in ("INCLUDED", "EXCLUDED")


def assert_relist_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert isinstance(data["relist_count_before"], int) and data["relist_count_before"] >= 0
    assert isinstance(data["price_reduction_pct"], (int, float))
    assert isinstance(data["new_list_price_cents"], int)
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_listing_summary(data: dict):
    """Marketing summary shape (PRD §3.6)."""
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert data["lifecycle_status"] in (
        "DRAFT", "PENDING_REVIEW", "COMPLIANCE_HOLD", "ACTIVE",
        "UNDER_CONTRACT", "SOLD", "WITHDRAWN", "EXPIRED",
    )
    assert data["syndication_posture"] in (
        "NOT_SYNDICATED", "SYNDICATING", "SYNDICATED", "DEGRADED", "SUSPENDED"
    )
    raw = data.get("feedback_score_raw")
    assert raw is None or isinstance(raw, (int, float))
    weighted = data.get("feedback_score_weighted")
    assert weighted is None or isinstance(weighted, (int, float))
    assert isinstance(data["audited_breach_count"], int)
    assert isinstance(data["provisional_breach_count"], int)
    headline = data.get("headline_display_price_cents")
    assert headline is None or isinstance(headline, int)
    assert isinstance(data["relist_count"], int)
