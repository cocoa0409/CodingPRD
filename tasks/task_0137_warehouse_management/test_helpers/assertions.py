"""Entity assertions and domain invariant checkers for the Warehouse Management API.

Each assert_{entity} validates the common identity/timestamp/version fields plus
the entity-specific fields and enum domains. ReceiptEvent omits updated_at/version
(PRD 2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_sku(data: dict):
    _assert_common(data)
    assert isinstance(data["sku_code"], str) and len(data["sku_code"]) > 0
    assert isinstance(data["description"], str)
    assert data["abc_class"] in ("A", "B", "C")
    assert isinstance(data["min_qty"], int) and data["min_qty"] >= 0
    assert isinstance(data["max_qty"], int) and data["max_qty"] > data["min_qty"]
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["available_qty"], int)
    assert isinstance(data["cycle_count_due"], bool)
    assert_sku_invariants(data)


def assert_sku_invariants(data: dict):
    """Quantity invariants that must always hold on a Sku (PRD 3.1)."""
    assert data["on_hand_qty"] >= 0, "on_hand_qty must never be negative"
    assert data["available_qty"] >= 0, "available_qty must never be negative"
    assert data["available_qty"] <= data["on_hand_qty"], (
        "available_qty must not exceed on_hand_qty"
    )


def assert_location(data: dict):
    _assert_common(data)
    assert isinstance(data["location_code"], str) and len(data["location_code"]) > 0
    assert data["zone"] in ("RECEIVING", "RESERVE", "PICK_FACE", "CROSS_DOCK", "STAGING")
    assert data["status"] in ("AVAILABLE", "BLOCKED")
    assert isinstance(data["used_volume_cm3"], (int, float))
    assert data["used_volume_cm3"] >= 0, "used_volume_cm3 must never be negative"
    assert data["used_volume_cm3"] <= data["max_volume_cm3"], (
        "used_volume_cm3 must not exceed max_volume_cm3"
    )


def assert_license_plate(data: dict):
    _assert_common(data)
    assert isinstance(data["lpn_code"], str) and len(data["lpn_code"]) > 0
    assert is_valid_uuid(data.get("sku_id", "")), "sku_id must be a valid UUID"
    assert isinstance(data["qty"], int) and data["qty"] >= 0, "qty must be a non-negative integer"
    assert data["disposition"] in (
        "PUTAWAY_PENDING", "STORED", "ALLOCATED", "PICKED_STAGED", "SHIPPED", "DEPLETED"
    )


def assert_inbound_asn(data: dict):
    _assert_common(data)
    assert isinstance(data["asn_number"], str) and len(data["asn_number"]) > 0
    assert isinstance(data["supplier_name"], str)
    assert data["handling_mode"] in ("PUTAWAY", "CROSS_DOCK")
    assert data["status"] in (
        "ANNOUNCED", "RECEIVING", "PUT_AWAY", "CROSS_DOCKED", "CLOSED", "CANCELLED"
    )


def assert_asn_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asn_id", "")), "asn_id must be a valid UUID"
    assert is_valid_uuid(data.get("sku_id", "")), "sku_id must be a valid UUID"
    assert isinstance(data["expected_qty"], int) and data["expected_qty"] > 0
    assert isinstance(data["received_qty"], int) and data["received_qty"] >= 0
    assert data["line_status"] in ("OPEN", "SATISFIED", "OVER")


def assert_receipt_event(data: dict):
    """Append-only record (PRD 2.4): id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("lpn_id", "")), "lpn_id must be a valid UUID"
    assert isinstance(data["received_qty"], int) and data["received_qty"] > 0
    assert "updated_at" not in data, "ReceiptEvent must not carry updated_at"
    assert "version" not in data, "ReceiptEvent must not carry version"


def assert_putaway_task(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("lpn_id", "")), "lpn_id must be a valid UUID"
    assert data["status"] in ("CREATED", "ASSIGNED", "COMPLETED", "CANCELLED")


def assert_outbound_order(data: dict):
    _assert_common(data)
    assert isinstance(data["order_number"], str) and len(data["order_number"]) > 0
    assert isinstance(data["priority"], int) and data["priority"] >= 1
    assert data["status"] in (
        "OPEN", "WAVED", "PICKING", "PICKED", "SHIPPED", "CANCELLED"
    )


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a valid UUID"
    assert is_valid_uuid(data.get("sku_id", "")), "sku_id must be a valid UUID"
    assert isinstance(data["ordered_qty"], int) and data["ordered_qty"] > 0
    assert isinstance(data["allocated_qty"], int) and data["allocated_qty"] >= 0
    assert isinstance(data["picked_qty"], int) and data["picked_qty"] >= 0


def assert_inventory_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_line_id", "")), "order_line_id must be a valid UUID"
    assert is_valid_uuid(data.get("lpn_id", "")), "lpn_id must be a valid UUID"
    assert isinstance(data["allocated_qty"], int) and data["allocated_qty"] > 0
    assert data["status"] in ("RESERVED", "COMMITTED", "RELEASED")


def assert_wave(data: dict):
    _assert_common(data)
    assert isinstance(data["wave_label"], str) and len(data["wave_label"]) > 0
    assert data["release_status"] in ("PLANNING", "RELEASED", "CLOSED")
    assert data["fulfillment_status"] in ("UNALLOCATED", "ALLOCATED", "PICKING", "PICKED")


def assert_pick_task(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("wave_id", "")), "wave_id must be a valid UUID"
    assert is_valid_uuid(data.get("allocation_id", "")), "allocation_id must be a valid UUID"
    assert isinstance(data["light_confirmed"], bool)
    assert data["status"] in ("PENDING", "IN_PROGRESS", "PICKED", "SHORT", "CANCELLED")


def assert_cycle_count(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a valid UUID"
    assert is_valid_uuid(data.get("sku_id", "")), "sku_id must be a valid UUID"
    assert isinstance(data["system_qty"], int)
    assert isinstance(data["variance_qty"], int)
    assert data["status"] in ("OPEN", "COUNTED", "RECONCILED", "REJECTED")


def assert_replenishment_task(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sku_id", "")), "sku_id must be a valid UUID"
    assert isinstance(data["replen_qty"], int)
    assert data["status"] in ("CREATED", "ASSIGNED", "COMPLETED", "CANCELLED")
