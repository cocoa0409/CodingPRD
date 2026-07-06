"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _has_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), \
        f"version must be int, got {type(data.get('version'))}"


def assert_sku(data: dict):
    _has_common_fields(data)
    assert isinstance(data["sku_code"], str) and len(data["sku_code"]) > 0
    assert data["category"] in {
        "BALLOON_LATEX", "BALLOON_FOIL", "COSTUME", "TABLEWARE",
        "DECOR", "PRINT_CUSTOM", "HELIUM", "SEASONAL_HALLOWEEN",
    }
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert isinstance(data["is_clearance"], bool)


def assert_bundle(data: dict):
    _has_common_fields(data)
    assert isinstance(data["bundle_code"], str) and len(data["bundle_code"]) > 0
    assert isinstance(data["bundle_price_cents"], int) and data["bundle_price_cents"] >= 0
    assert data["status"] in {"ACTIVE", "DISCONTINUED"}


def assert_customer(data: dict):
    _has_common_fields(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0


def assert_order(data: dict):
    _has_common_fields(data)
    assert data["fulfillment_status"] in {
        "DRAFT", "RESERVED", "PICKING", "READY_FOR_PICKUP",
        "PICKED_UP", "DELIVERED", "RETURNED", "CANCELLED",
    }
    assert data["payment_status"] in {
        "UNPAID", "DEPOSIT_HELD", "PAID", "PARTIALLY_REFUNDED", "REFUNDED",
    }
    assert data["channel"] in {"BOPIS", "DELIVERY", "IN_STORE"}


def assert_helium_tank(data: dict):
    _has_common_fields(data)
    assert isinstance(data["tank_code"], str) and len(data["tank_code"]) > 0
    assert isinstance(data["capacity_cubic_ft"], int) and data["capacity_cubic_ft"] >= 0
    assert isinstance(data["remaining_cubic_ft"], int)
    assert 0 <= data["remaining_cubic_ft"] <= data["capacity_cubic_ft"]
    assert data["status"] in {"ACTIVE", "EMPTY", "OUT_OF_SERVICE"}


def assert_delivery_slot(data: dict):
    _has_common_fields(data)
    assert data["status"] in {"AVAILABLE", "RESERVED", "COMPLETED", "CANCELLED"}


def assert_rental_contract(data: dict):
    _has_common_fields(data)
    assert data["status"] in {"RESERVED", "PICKED_UP", "RETURNED", "LATE_RETURN", "DAMAGED"}
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0


def assert_custom_print_order(data: dict):
    _has_common_fields(data)
    assert data["status"] in {
        "DRAFT", "PROOF_SENT", "REVISION_REQUESTED", "APPROVED",
        "PRINTING", "READY", "CANCELLED",
    }
    assert isinstance(data["revision_count"], int) and 0 <= data["revision_count"] <= 3


def assert_event_package(data: dict):
    _has_common_fields(data)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert 0 <= data["deposit_pct"] <= 1
    assert data["min_lead_days"] >= 0


def assert_event_booking(data: dict):
    _has_common_fields(data)
    assert data["status"] in {"HELD", "CONFIRMED", "COMPLETED", "CANCELLED", "FORFEITED"}
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
