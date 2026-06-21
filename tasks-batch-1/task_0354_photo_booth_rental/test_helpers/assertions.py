"""Entity assertions and domain invariant checkers (Photo Booth Rental API)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)

_BOOTH_TYPES = ["OPEN_AIR", "ENCLOSED", "MIRROR", "ROAMING_360"]
_BOOTH_STATUSES = ["AVAILABLE", "MAINTENANCE", "RETIRED"]
_ATTENDANT_STATUSES = ["AVAILABLE", "ON_LEAVE", "INACTIVE"]
_SCHEDULE_STATUSES = ["DRAFT", "CONFIRMED", "IN_SERVICE", "COMPLETED", "CANCELLED"]
_PAYMENT_STATUSES = ["UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED", "FORFEITED"]
_ADDON_CODES = ["PROPS", "BACKDROP", "ATTENDANT", "ALBUM"]
_PAYMENT_KINDS = ["DEPOSIT", "BALANCE", "REFUND"]
_ASSIGNMENT_STATUSES = ["ACTIVE", "RELEASED"]
_GALLERY_STATUSES = ["DRAFT", "PUBLISHED", "UNPUBLISHED"]


def _assert_common(data: dict):
    """id + created_at + updated_at + version (common_fields: true)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_booth_model(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["booth_type"] in _BOOTH_TYPES
    assert isinstance(data["footprint_sqft"], int) and data["footprint_sqft"] >= 1
    assert isinstance(data["max_prints_per_hour"], int) and data["max_prints_per_hour"] >= 0
    assert isinstance(data["active"], bool)


def assert_package(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booth_model_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["base_price"] >= 0
    assert_cost_precision(data["base_price"])
    assert isinstance(data["included_hours"], int) and data["included_hours"] >= 1
    assert isinstance(data["included_prints"], int) and data["included_prints"] >= 0
    for rate in ("overtime_rate_per_hour", "idle_rate_per_hour", "overage_print_rate"):
        assert data[rate] >= 0
    assert isinstance(data["active"], bool)


def assert_booth(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booth_model_id"])
    assert isinstance(data["asset_tag"], str) and len(data["asset_tag"]) > 0
    assert data["status"] in _BOOTH_STATUSES


def assert_attendant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in _ATTENDANT_STATUSES


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["package_id"])
    assert data["schedule_status"] in _SCHEDULE_STATUSES
    assert data["payment_status"] in _PAYMENT_STATUSES
    assert is_iso8601_timestamp(data["event_start"])
    assert is_iso8601_timestamp(data["event_end"])
    assert isinstance(data["venue_distance_miles"], int) and data["venue_distance_miles"] >= 0
    for money in ("quote_subtotal", "deposit_due", "balance_due", "travel_fee",
                  "amount_paid", "amount_refunded"):
        assert isinstance(data[money], (int, float)), f"{money} must be numeric"
        assert_cost_precision(data[money])


def assert_add_on(data: dict):
    _assert_common(data)
    assert data["code"] in _ADDON_CODES
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["unit_price"] >= 0
    assert_cost_precision(data["unit_price"])
    assert isinstance(data["requires_attendant"], bool)
    assert isinstance(data["max_qty"], int) and data["max_qty"] >= 1


def assert_booking_add_on(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["add_on_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["line_total"] >= 0
    assert_cost_precision(data["line_total"])


def assert_attendant_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["attendant_id"])
    assert data["status"] in _ASSIGNMENT_STATUSES


def assert_event_log(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["finalized"], bool)


def assert_gallery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["photo_count"], int) and data["photo_count"] >= 0
    assert data["status"] in _GALLERY_STATUSES


def assert_payment(data: dict):
    """Payment is common_fields: false (append-only): id + created_at only,
    NO updated_at, NO version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["booking_id"])
    assert data["kind"] in _PAYMENT_KINDS
    assert data["amount"] > 0
    assert_cost_precision(data["amount"])
