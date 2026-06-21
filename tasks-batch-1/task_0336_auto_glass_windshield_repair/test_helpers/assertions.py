"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["service_address_state"], str)


def assert_vehicle(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["vin"], str)
    assert isinstance(data["adas_equipped"], bool)
    assert isinstance(data["model_year"], int)


def assert_work_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "OPEN", "ASSESSED", "SCHEDULED", "IN_SERVICE",
        "AWAITING_RECALIBRATION", "CURING", "COMPLETED", "CANCELLED",
    ], f"unexpected work order status {data['status']!r}"
    assert data["service_decision"] in ["REPAIR", "REPLACE", None]
    assert data["service_location"] in ["MOBILE", "IN_SHOP", None]
    assert isinstance(data["recalibration_required"], bool)
    assert isinstance(data["total_charge_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)


def assert_damage_assessment(data: dict):
    assert_common_fields(data)
    assert data["recommendation"] in ["REPAIR", "REPLACE"]
    assert data["status"] in ["DRAFT", "ACCEPTED", "SUPERSEDED"]


def assert_glass_part(data: dict):
    assert_common_fields(data)
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_qty"], int)
    assert isinstance(data["adas_compatible"], bool)


def assert_part_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING", "RESERVED", "BACKORDERED", "CONSUMED", "CANCELLED"]


def assert_service_appointment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["BOOKED", "CHECKED_IN", "RELEASED", "CANCELLED"]
    assert data["service_location"] in ["MOBILE", "IN_SHOP"]


def assert_recalibration_job(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED", "CANCELLED"]
    assert data["calibration_type"] in ["STATIC", "DYNAMIC"]


def assert_payment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["CAPTURED", "REFUNDED"]
    assert isinstance(data["amount_cents"], int)


def assert_warranty(data: dict):
    assert_common_fields(data)
    assert data["coverage_type"] in ["CHIP_REPAIR", "LIFETIME_LEAK"]
    assert data["status"] in ["ACTIVE", "VOID"]


def assert_glass_units_conserved(part: dict, expected_total: int):
    """The conserved quantity is on_hand_qty + reserved_qty (PRD 2.9)."""
    total = part["on_hand_qty"] + part["reserved_qty"]
    assert total == expected_total, (
        f"glass units not conserved: on_hand {part['on_hand_qty']} + "
        f"reserved {part['reserved_qty']} = {total}, expected {expected_total}"
    )
