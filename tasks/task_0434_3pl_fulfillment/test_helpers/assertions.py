"""Entity assertions and domain invariant checkers for the 3PL fulfillment API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be int >= 1"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["storage_rate_per_pallet_cents"], int)
    assert isinstance(data["handling_rate_per_order_cents"], int)
    assert isinstance(data["handling_rate_per_extra_unit_cents"], int)
    assert isinstance(data["handling_surcharge_per_extra_carton_cents"], int)
    assert isinstance(data["carrier_discount_bps"], int)
    assert 0 <= data["carrier_discount_bps"] <= 10000
    assert isinstance(data["storage_balance_cents"], int)
    assert isinstance(data["handling_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_sku(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["unit_volume_cc"], int)
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["hazmat"], bool)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_bin(data: dict):
    _assert_common(data)
    assert isinstance(data["location_code"], str) and len(data["location_code"]) > 0
    assert data["bin_type"] in ("GENERAL", "PALLET")
    assert isinstance(data["capacity_cc"], int)
    assert isinstance(data["occupied_cc"], int)
    assert data["status"] in ("OPEN", "BLOCKED")


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["sku_id"])
    assert is_valid_uuid(data["bin_id"])
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_qty"], int)
    assert isinstance(data["available_qty"], int)
    # Fixed inventory relationship (PRD §2.8).
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        f"available_qty must equal on_hand_qty - reserved_qty, got "
        f"{data['available_qty']} != {data['on_hand_qty']} - {data['reserved_qty']}"
    )
    assert data["available_qty"] >= 0


def assert_receipt(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["sku_id"])
    assert is_valid_uuid(data["bin_id"])
    assert isinstance(data["expected_qty"], int)
    assert isinstance(data["received_qty"], int)
    assert data["status"] in ("ANNOUNCED", "RECEIVED", "PUTAWAY", "CANCELLED")


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["ship_to_zone"], int)
    assert isinstance(data["total_units"], int)
    assert isinstance(data["estimated_handling_cents"], int)
    assert isinstance(data["billed_handling_cents"], int)
    assert data["status"] in (
        "IMPORTED", "RESERVED", "PICKING", "PACKED", "SHIPPED", "CANCELLED", "SHORT",
    )


def assert_wave(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["order_count"], int)
    assert data["status"] in ("BUILDING", "RELEASED", "COMPLETED", "CANCELLED")


def assert_pick_task(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["qty"], int)
    assert isinstance(data["picked_qty"], int)
    assert data["status"] in ("ASSIGNED", "PICKED", "SHORT_CLOSED")


def assert_carton(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["packed_units"], int)
    assert isinstance(data["fill_volume_cc"], int)
    assert data["carton_size"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["status"] in ("PACKED", "SHIPPED", "VOIDED")


def assert_shipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert data["carrier"] in ("GROUND_ECONOMY", "GROUND_PLUS", "AIR_EXPRESS")
    assert isinstance(data["quoted_cost_cents"], int)
    assert isinstance(data["tracking_number"], str) and len(data["tracking_number"]) > 0
    assert data["status"] in ("LABELLED", "DELIVERED", "VOIDED")


def assert_return(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["qty"], int)
    assert data["status"] in ("REQUESTED", "GRADED", "CLOSED")
    if data.get("grade") is not None:
        assert data["grade"] in ("SELLABLE", "DAMAGED")


def assert_cycle_count(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["counted_qty"], int)
    assert isinstance(data["variance_qty"], int)
    assert data["status"] == "APPLIED"


def assert_billing_charge(data: dict):
    """BillingCharge is append-only: only id + created_at, no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["client_id"])
    assert data["charge_type"] in ("STORAGE", "HANDLING")
    assert isinstance(data["amount_cents"], int)
    assert data["posted"] is True


def assert_appendonly_no_audit_fields(data: dict):
    """A BillingCharge response must NOT carry version or updated_at (PRD §2.4)."""
    assert "version" not in data, "BillingCharge response must not carry a 'version' field"
    assert "updated_at" not in data, "BillingCharge response must not carry an 'updated_at' field"
