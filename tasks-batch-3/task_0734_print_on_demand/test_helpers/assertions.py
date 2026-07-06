"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict) -> None:
    """Fields present on every common_fields=true entity."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1: {data.get('version')!r}"


def assert_creator(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["display_name"], str)
    assert isinstance(data["payout_country_code"], str) and len(data["payout_country_code"]) == 2
    assert isinstance(data["payout_wallet_cents"], int)
    assert data["verification_status"] in ("UNVERIFIED", "PENDING", "VERIFIED", "REJECTED")
    assert isinstance(data["default_payout_fee_bps"], int)
    assert isinstance(data["reprint_strike_count"], int)


def assert_storefront(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["creator_id"])
    assert isinstance(data["slug"], str) and len(data["slug"]) > 0
    assert data["integration_channel"] in ("NATIVE", "ETSY", "SHOPIFY")
    assert data["integration_status"] in ("NONE", "LINKED", "SUSPENDED")
    assert isinstance(data["markup_bps"], int)
    assert 0 <= data["markup_bps"] <= 10000


def assert_product(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["sku"], str)
    assert data["category"] in ("APPAREL", "DRINKWARE", "ACCESSORY", "PRINT")
    assert isinstance(data["base_cost_cents"], int)
    assert data["base_cost_cents"] >= 100
    assert isinstance(data["dimensions_json"], dict)


def assert_variant(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["color"], str)
    assert isinstance(data["size"], str)
    assert isinstance(data["base_cost_delta_cents"], int)
    assert isinstance(data["active"], bool)


def assert_design(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["creator_id"])
    assert isinstance(data["file_hash"], str)
    assert data["status"] in ("UPLOADED", "MOCKUP_READY", "APPROVED", "REJECTED")


def assert_listing(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["storefront_id"])
    assert is_valid_uuid(data["design_id"])
    assert is_valid_uuid(data["variant_id"])
    assert isinstance(data["title"], str)
    assert isinstance(data["listed_price_cents"], int)
    assert data["listed_price_cents"] >= 0
    assert data["status"] in ("DRAFT", "PUBLISHED", "ARCHIVED")


def assert_fulfillment_partner(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["cost_multiplier_bps"], int)
    assert isinstance(data["current_backlog_hours"], int)
    assert data["current_backlog_hours"] >= 0
    assert isinstance(data["max_backlog_hours"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "RETIRED")


def assert_order(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["storefront_id"])
    assert is_valid_uuid(data["listing_id"])
    assert isinstance(data["buyer_email"], str)
    assert isinstance(data["ship_country_code"], str) and len(data["ship_country_code"]) == 2
    assert isinstance(data["item_count"], int)
    assert data["item_count"] >= 1
    assert isinstance(data["is_sample"], bool)
    assert data["payment_status"] in (
        "DRAFT", "AUTHORIZED", "CAPTURED", "REFUND_PARTIAL", "REFUND_FULL", "VOIDED"
    )
    assert data["fulfillment_status"] in (
        "PENDING", "ROUTED", "IN_PRINT", "SHIPPED", "DELIVERED", "CANCELLED"
    )
    assert isinstance(data["creator_net_cents"], int)


def assert_fulfillment_job(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["partner_id"])
    assert data["status"] in (
        "QUEUED", "PRINTING", "SHIPPED", "DELIVERED", "FAILED", "REPRINT_REQUESTED", "CANCELLED"
    )
    assert isinstance(data["reprint_generation"], int)
    assert data["reprint_generation"] >= 0
    assert isinstance(data["partner_charge_cents"], int)


def assert_reprint_request(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["job_id"])
    assert data["fault_category"] in ("PARTNER_FAULT", "CONSUMER_FAULT", "PLATFORM_GESTURE")
    assert isinstance(data["reason_code"], str)
    assert data["status"] in ("OPEN", "APPROVED", "DENIED")


def assert_payout_cycle(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["creator_id"])
    assert isinstance(data["cycle_start"], str)
    assert isinstance(data["cycle_end"], str)
    assert data["status"] in ("DRAFT", "RELEASED", "RETURNED")


def assert_channel_sync_event(data: dict) -> None:
    """Append-only entity — only id + created_at + entity-specific fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    # No updated_at, no version — append-only
    assert data["channel"] in ("ETSY", "SHOPIFY")
    assert data["event_type"] in ("LISTING_MIRROR", "ORDER_INGEST", "SYNC_FAIL")
