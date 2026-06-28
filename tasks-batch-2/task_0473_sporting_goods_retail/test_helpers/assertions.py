"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates structural shape against the PRD contract.
Domain-invariant checkers express rules that must hold after any operation
(e.g. the inventory derived-field identity available_qty == on_hand - reserved).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id/created_at/updated_at/version for entities with the full field set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_sku(data: dict):
    _assert_common(data)
    assert data["sport"] in ["HOCKEY", "BASEBALL", "FOOTWEAR", "FISHING", "TEAMWEAR", "APPAREL"]
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["size_label"], str)
    assert isinstance(data["is_footwear"], bool)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["requires_license_permit"], bool)
    assert isinstance(data["embroiderable"], bool)
    assert data["lifecycle"] in ["STANDARD", "SEASONAL", "CLEARANCE", "DISCONTINUED"]
    # active_markdown_id is a uuid pointer or null
    assert data["active_markdown_id"] is None or is_valid_uuid(data["active_markdown_id"])
    # is_footwear is derived: true exactly when sport == FOOTWEAR
    assert data["is_footwear"] == (data["sport"] == "FOOTWEAR")


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["ship_from_store_enabled"], bool)
    assert isinstance(data["pickup_enabled"], bool)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["home_state_code"], str) and len(data["home_state_code"]) == 2
    assert isinstance(data["loyalty_points"], int) and data["loyalty_points"] >= 0
    assert data["loyalty_tier"] in ["BRONZE", "SILVER", "GOLD", "PLATINUM"]


def assert_store_inventory(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert isinstance(data["available_qty"], int) and data["available_qty"] >= 0
    assert_inventory_invariants(data)


def assert_inventory_invariants(data: dict):
    """PRD §2.5: available_qty == on_hand_qty - reserved_qty, none negative."""
    assert data["on_hand_qty"] >= 0, "on_hand_qty never negative"
    assert data["reserved_qty"] >= 0, "reserved_qty never negative"
    assert data["available_qty"] >= 0, "available_qty never negative"
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        f"available_qty {data['available_qty']} must equal on_hand "
        f"{data['on_hand_qty']} - reserved {data['reserved_qty']}"
    )


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["store_id"])
    assert data["fulfillment_type"] in ["BOPIS", "SFS"]
    assert data["payment_status"] in ["UNPAID", "AUTHORIZED", "CAPTURED", "REFUNDED"]
    assert data["fulfillment_status"] in ["DRAFT", "RESERVED", "READY", "FULFILLED", "CANCELLED"]
    assert isinstance(data["provisional_total_cents"], int)
    assert data["final_total_cents"] is None or isinstance(data["final_total_cents"], int)
    assert isinstance(data["loyalty_points_awarded"], int)


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert data["embroidery_text"] is None or isinstance(data["embroidery_text"], str)
    assert data["line_status"] in ["RESERVED", "COMMITTED", "RELEASED"]


def assert_service_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["store_id"])
    assert data["service_type"] in ["SKATE_SHARPEN", "RACKET_STRING"]
    assert data["part_sku_id"] is None or is_valid_uuid(data["part_sku_id"])
    assert data["status"] in ["RECEIVED", "IN_PROGRESS", "NEEDS_PARTS", "COMPLETED", "CANCELLED"]
    assert isinstance(data["service_fee_cents"], int)


def assert_fishing_license(data: dict):
    """PRD §2.4: FishingLicense carries only id + created_at — NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "FishingLicense must not expose a version field"
    assert "updated_at" not in data, "FishingLicense must not expose an updated_at field"
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["issuing_store_id"])
    assert data["residency"] in ["RESIDENT", "NONRESIDENT"]
    assert data["status"] in ["ACTIVE", "EXPIRED"]
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_price_match_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["order_line_id"])
    assert isinstance(data["competitor_price_cents"], int) and data["competitor_price_cents"] >= 0
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED"]
    assert (data["approved_unit_price_cents"] is None
            or isinstance(data["approved_unit_price_cents"], int))


def assert_markdown(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sku_id"])
    assert data["markdown_kind"] in ["SEASONAL", "CLEARANCE"]
    assert isinstance(data["percent_off"], int) and 1 <= data["percent_off"] <= 90
    assert data["status"] in ["SCHEDULED", "ACTIVE", "EXPIRED"]


def assert_team_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["team_name"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]
    assert isinstance(data["total_units"], int) and data["total_units"] >= 0
    assert data["spawned_order_id"] is None or is_valid_uuid(data["spawned_order_id"])


def assert_team_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["team_order_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
