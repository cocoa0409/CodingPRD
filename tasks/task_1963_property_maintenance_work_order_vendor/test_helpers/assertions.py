"""Entity assertions and domain invariant checkers.

Timestamps are compared as instants (not raw strings): the PRD pins the
logical instant of every stamped field but allows any ISO 8601 UTC rendering
with three fractional digits, so equality is judged after parsing.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ChargebackStatus,
    EntryAuthorization,
    Priority,
    PurchaseRequestStatus,
    RestockStatus,
    Trade,
    VendorStatus,
    WorkOrderPartStatus,
    WorkOrderStatus,
)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating optional fractional digits."""
    assert isinstance(value, str) and value.strip(), f"expected ISO timestamp string, got {value!r}"
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_instant_equals(actual: str, expected_iso: str, label: str = "timestamp") -> None:
    """Assert two ISO timestamps denote the same instant, regardless of rendering."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_property(data: dict) -> None:
    _assert_common_fields(data, "Property")
    assert isinstance(data["name"], str) and data["name"]
    for field in (
        "emergency_response_hours",
        "emergency_completion_hours",
        "urgent_response_hours",
        "urgent_completion_hours",
        "routine_response_hours",
        "routine_completion_hours",
        "purchase_auto_approve_threshold_cents",
        "recall_window_days",
        "vendor_travel_buffer_minutes",
        "entry_notice_min_hours",
    ):
        assert isinstance(data[field], int), f"Property.{field} must be an integer"


def assert_resident(data: dict) -> None:
    _assert_common_fields(data, "Resident")
    assert is_valid_uuid(data.get("property_id", "")), "Resident.property_id must be a UUID"
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["chargeback_balance_cents"], int)
    assert data["chargeback_balance_cents"] >= 0


def assert_technician(data: dict) -> None:
    _assert_common_fields(data, "Technician")
    assert data["trade"] in [t.value for t in Trade]


def assert_vendor(data: dict) -> None:
    _assert_common_fields(data, "Vendor")
    assert data["trade"] in [t.value for t in Trade]
    assert data["status"] in [s.value for s in VendorStatus]
    assert is_iso8601_timestamp(data.get("insurance_valid_until", ""))


def assert_part(data: dict) -> None:
    _assert_common_fields(data, "Part")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["quantity_on_hand"], int)
    assert isinstance(data["reserved_quantity"], int)
    assert data["restock_status"] in [s.value for s in RestockStatus]


def assert_work_order(data: dict) -> None:
    _assert_common_fields(data, "WorkOrder")
    assert data["status"] in [s.value for s in WorkOrderStatus]
    assert data["category"] in [t.value for t in Trade]
    assert data["priority"] in [p.value for p in Priority]
    assert isinstance(data["recall_count"], int) and data["recall_count"] >= 0
    assert isinstance(data["resident_signoff"], bool)
    assert isinstance(data["parts_total_cents"], int)
    assert isinstance(data["response_sla_breached"], bool)
    assert isinstance(data["completion_sla_breached"], bool)
    assert is_iso8601_timestamp(data.get("response_due_at", ""))
    assert is_iso8601_timestamp(data.get("completion_due_at", ""))
    if data.get("entry_authorization") is not None:
        assert data["entry_authorization"] in [e.value for e in EntryAuthorization]


def assert_work_order_part(data: dict) -> None:
    _assert_common_fields(data, "WorkOrderPart")
    assert data["status"] in [s.value for s in WorkOrderPartStatus]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_cost_cents_snapshot"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["line_total_cents"] == data["quantity"] * data["unit_cost_cents_snapshot"], (
        "line_total_cents must equal quantity * unit_cost_cents_snapshot"
    )


def assert_purchase_request(data: dict) -> None:
    _assert_common_fields(data, "PurchaseRequest")
    assert data["status"] in [s.value for s in PurchaseRequestStatus]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["items_subtotal_cents"], int)
    assert isinstance(data["handling_fee_cents"], int)
    assert isinstance(data["estimated_total_cents"], int)
    assert isinstance(data["auto_approved"], bool)
    assert data["estimated_total_cents"] == (
        data["items_subtotal_cents"] + data["shipping_fee_cents"] + data["handling_fee_cents"]
    ), "estimated_total_cents must equal subtotal + shipping + handling"


def assert_chargeback(data: dict) -> None:
    _assert_common_fields(data, "Chargeback")
    assert data["status"] in [s.value for s in ChargebackStatus]
    assert isinstance(data["provisional_amount_cents"], int)


def assert_part_stock_invariant(part: dict) -> None:
    """Ledger invariant from the PRD stock-ledger rule: restock_status reflects
    quantity_on_hand vs reorder_level (equality counts as low stock)."""
    if part["quantity_on_hand"] <= part["reorder_level"]:
        assert part["restock_status"] == RestockStatus.LOW_STOCK.value, (
            f"expected LOW_STOCK at on_hand {part['quantity_on_hand']} <= reorder {part['reorder_level']}"
        )
    else:
        assert part["restock_status"] == RestockStatus.IN_STOCK.value, (
            f"expected IN_STOCK at on_hand {part['quantity_on_hand']} > reorder {part['reorder_level']}"
        )
