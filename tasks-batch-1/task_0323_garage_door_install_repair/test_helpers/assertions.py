"""Entity assertions and domain invariant checkers.

Validates the field set and types each PRD resource must return, plus the
quantity-conservation invariants of §2.9.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_reference_fields(data: dict):
    """Immutable reference data: id + created_at only, NO updated_at, NO version (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["service_address"], str)
    assert isinstance(data["time_zone"], str) and len(data["time_zone"]) > 0
    assert data["financing_standing"] in ("GOOD", "BLOCKED")
    assert isinstance(data["active_warranty_count"], int)
    assert data["active_warranty_count"] >= 0


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["skill_level"] in ("APPRENTICE", "CERTIFIED", "MASTER")
    assert isinstance(data["certified_for_install"], bool)
    assert data["status"] in ("AVAILABLE", "ON_LEAVE")
    assert isinstance(data["booked_minutes"], int)
    assert isinstance(data["jobs_completed_count"], int)
    assert isinstance(data["callback_rate_provisional"], (int, float))
    assert isinstance(data["callback_rate_settled"], (int, float))


def assert_door_model(data: dict):
    _assert_reference_fields(data)
    assert "version" not in data, "DoorModel is immutable reference data — must have no version (§2.4)"
    assert "updated_at" not in data, "DoorModel is immutable reference data — must have no updated_at (§2.4)"
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["width_in"], int)
    assert isinstance(data["height_in"], int)
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["install_labor_minutes"], int)
    assert isinstance(data["requires_lift"], bool)


def assert_opener_model(data: dict):
    _assert_reference_fields(data)
    assert "version" not in data, "OpenerModel is immutable reference data — must have no version (§2.4)"
    assert "updated_at" not in data, "OpenerModel is immutable reference data — must have no updated_at (§2.4)"
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["install_labor_minutes"], int)


def assert_part(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in ("SPRING", "CABLE", "PANEL", "ROLLER", "SENSOR")
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["markup_pct"], (int, float))
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_qty"], int)
    assert isinstance(data["available_qty"], int)
    assert_part_inventory_invariant(data)


def assert_part_inventory_invariant(data: dict):
    """§2.9: available_qty == on_hand_qty - reserved_qty, never below zero."""
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        f"available_qty ({data['available_qty']}) must equal on_hand_qty "
        f"({data['on_hand_qty']}) - reserved_qty ({data['reserved_qty']})"
    )
    assert data["available_qty"] >= 0, "available_qty must never fall below zero"
    assert data["reserved_qty"] >= 0, "reserved_qty must never be negative"


def assert_equipment_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["concurrent_capacity"], int)


def assert_quote(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["quote_type"] in ("SERVICE_CALL", "INSTALL")
    assert data["status"] in ("DRAFT", "SENT", "ACCEPTED", "DECLINED", "EXPIRED")
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["service_call_fee_cents"], int)
    assert isinstance(data["estimate_total_cents"], int)


def assert_quote_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["quote_id"])
    assert data["item_kind"] in ("PART", "DOOR", "OPENER", "LABOR")
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["quote_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["dispatch_status"] in (
        "UNSCHEDULED", "SCHEDULED", "EN_ROUTE", "ON_SITE", "COMPLETED", "CLOSED", "CANCELLED",
    )
    assert data["billing_status"] in ("PENDING", "INVOICED", "PAID")
    assert isinstance(data["is_emergency"], bool)
    assert isinstance(data["safety_inspection_passed"], bool)
    assert isinstance(data["final_total_cents"], int)
    assert isinstance(data["emergency_surcharge_cents"], int)


def assert_part_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert is_valid_uuid(data["part_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["status"] in ("HELD", "CONSUMED", "RELEASED")


def assert_warranty_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["tune_ups_included"], int)
    assert isinstance(data["tune_ups_used"], int)
    assert data["status"] in ("PENDING", "ACTIVE", "EXPIRED", "CANCELLED")


def assert_financing_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["quote_id"])
    assert isinstance(data["principal_cents"], int)
    assert data["term_months"] in (6, 12, 24)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DECLINED", "ACTIVE", "DEFAULTED")


def assert_callback(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert isinstance(data["reason"], str)
    assert data["status"] in ("OPEN", "SCHEDULED", "ON_SITE", "RESOLVED")
    assert isinstance(data["fault_confirmed"], bool)
