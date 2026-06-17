"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response structure against the PRD contract.
Immutable config resources (MembershipPlan, FlatRateItem, Part) must NOT carry
updated_at / version (PRD §2.4); the assertions enforce their absence.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields for versioned resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_config_common(data: dict):
    """Common fields for immutable config resources: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "config resource must not emit updated_at"
    assert "version" not in data, "config resource must not emit version"


def assert_membership_plan(data: dict):
    _assert_config_common(data)
    assert data["tier_code"] in ["NONE", "SILVER", "GOLD"]
    assert isinstance(data["name"], str)
    assert 0 <= data["labor_discount_pct"] <= 1
    assert isinstance(data["waives_trip_fee"], bool)
    assert isinstance(data["annual_fee_cents"], int)


def assert_flat_rate_item(data: dict):
    _assert_config_common(data)
    assert isinstance(data["code"], str)
    assert data["category"] in ["LEAK", "DRAIN", "WATER_HEATER", "REPIPE", "GENERAL"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert 1 <= data["skill_required"] <= 5
    assert isinstance(data["requires_permit"], bool)


def assert_part(data: dict):
    _assert_config_common(data)
    assert isinstance(data["sku"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["service_address"], str)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["committed_credit_cents"], int)
    assert data["committed_credit_cents"] >= 0, "committed_credit_cents must be non-negative"


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert 1 <= data["skill_level"] <= 5
    assert isinstance(data["licensed_for_permits"], bool)
    assert data["status"] in ["AVAILABLE", "ON_CALL", "OFF_DUTY"]
    assert isinstance(data["lifetime_completed_count"], int) and data["lifetime_completed_count"] >= 0
    assert isinstance(data["lifetime_callback_count"], int) and data["lifetime_callback_count"] >= 0
    assert isinstance(data["needs_restock_skus"], int) and data["needs_restock_skus"] >= 0


def assert_inspector(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["jurisdiction"], str)
    assert isinstance(data["max_daily_inspections"], int) and data["max_daily_inspections"] >= 1


def assert_truck_stock(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["technician_id"])
    assert is_valid_uuid(data["part_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 0
    assert isinstance(data["reorder_point"], int) and data["reorder_point"] >= 0
    assert isinstance(data["needs_restock"], bool)


def assert_service_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["category"] in ["LEAK", "DRAIN", "WATER_HEATER", "REPIPE"]
    assert data["priority"] in ["STANDARD", "EMERGENCY"]
    assert isinstance(data["after_hours"], bool)
    assert data["status"] in [
        "RECEIVED", "DISPATCHED", "EN_ROUTE", "ON_SITE", "AUTHORIZED",
        "IN_PROGRESS", "COMPLETED", "REOPENED", "CANCELLED",
    ]
    assert isinstance(data["authorized_amount_cents"], int)


def assert_dispatch_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["job_id"])
    assert is_valid_uuid(data["technician_id"])
    assert data["status"] in [
        "PROPOSED", "CONFIRMED", "EN_ROUTE", "ON_SITE", "CLOSED", "CANCELLED",
    ]


def assert_estimate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["job_id"])
    assert data["status"] in [
        "DRAFT", "PRESENTED", "REVISED", "APPROVED", "DECLINED", "CONSUMED",
    ]
    for field in ["labor_subtotal_cents", "parts_subtotal_cents", "discount_cents",
                  "trip_fee_cents", "emergency_surcharge_cents", "estimate_total_cents"]:
        assert isinstance(data[field], int), f"{field} must be an integer cents value"


def assert_estimate_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["estimate_id"])
    assert data["line_type"] in ["FLAT_RATE", "PART"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["job_id"])
    assert isinstance(data["jurisdiction"], str)
    assert data["status"] in [
        "APPLIED", "ISSUED", "INSPECTION_SCHEDULED", "PASSED", "FAILED", "VOIDED",
    ]
    assert isinstance(data["reapply_count"], int) and data["reapply_count"] >= 0


def assert_inspection_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["permit_id"])
    assert is_valid_uuid(data["inspector_id"])
    assert data["result"] in ["PENDING", "PASSED", "FAILED"]


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["job_id"])
    assert data["status"] in ["FINALIZED", "VOIDED"]
    for field in ["final_labor_cents", "final_parts_cents", "final_total_cents"]:
        assert isinstance(data[field], int), f"{field} must be an integer cents value"


def assert_callback(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["original_job_id"])
    assert isinstance(data["reason"], str)
    assert data["status"] in ["OPEN", "ACCEPTED", "REJECTED", "RESOLVED"]
    assert isinstance(data["within_warranty"], bool)
