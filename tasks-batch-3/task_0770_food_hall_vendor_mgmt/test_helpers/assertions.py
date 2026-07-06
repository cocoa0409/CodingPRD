"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_food_hall(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["total_seating_capacity"], int) and data["total_seating_capacity"] >= 1
    assert isinstance(data["common_area_capacity"], int) and data["common_area_capacity"] >= 1
    assert 0 <= data["hall_open_minutes"] < data["hall_close_minutes"] <= 1440
    assert isinstance(data["event_buffer_minutes"], int) and data["event_buffer_minutes"] >= 0


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["contact_email"], str)
    assert data["status"] in ("APPLIED", "ACTIVE", "SUSPENDED")


def assert_stall(data: dict):
    _assert_common(data)
    assert isinstance(data["stall_code"], str) and len(data["stall_code"]) > 0
    assert isinstance(data["size_sqft"], int) and data["size_sqft"] >= 1
    assert 0 <= data["open_minutes"] < data["close_minutes"] <= 1440
    assert data["operational_posture"] in ("OPEN", "RESTRICTED", "SUSPENDED")
    # current_lease_id / current_vendor_id are derived mirrors, null when vacant.
    assert data["current_lease_id"] is None or is_valid_uuid(data["current_lease_id"])
    assert data["current_vendor_id"] is None or is_valid_uuid(data["current_vendor_id"])


def assert_lease(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATED")
    assert isinstance(data["base_rent_cents"], int) and data["base_rent_cents"] >= 0
    assert 0 <= data["percentage_rate"] <= 1
    assert isinstance(data["natural_breakpoint_cents"], int) and data["natural_breakpoint_cents"] >= 0
    assert data["rent_cap_cents"] >= data["base_rent_cents"]
    assert isinstance(data["security_deposit_cents"], int) and data["security_deposit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_permit(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ISSUED", "SUSPENDED", "REVOKED")
    assert isinstance(data["permit_number"], str)


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "CONDUCTED")
    if data["status"] == "CONDUCTED":
        assert data["result"] in ("PASS", "CONDITIONAL", "FAIL")
        assert 0 <= data["score"] <= 100


def assert_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLACED", "ROUTED", "ACCEPTED", "FULFILLED", "REJECTED")
    assert isinstance(data["gross_amount_cents"], int) and data["gross_amount_cents"] >= 1
    assert isinstance(data["item_count"], int) and data["item_count"] >= 1


def assert_seating_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "RELEASED")
    assert isinstance(data["seats"], int) and data["seats"] >= 1


def assert_marketing_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "SCHEDULED", "CANCELLED")
    assert isinstance(data["reserved_capacity"], int) and data["reserved_capacity"] >= 1
    assert isinstance(data["expected_footfall"], int) and data["expected_footfall"] >= 0


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROVISIONAL", "DISPUTED", "FINALIZED", "VOIDED", "SUPERSEDED")
    for field in ("gross_sales_cents", "base_rent_charged_cents",
                  "percentage_rent_cents", "total_rent_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
        assert data[field] >= 0, f"{field} must be non-negative"
