"""Entity assertions and domain invariant checkers for the Print & Copy Shop Order API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id (UUID), created_at/updated_at (ISO8601), integer version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_shop(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["tax_rate_bps"], int)
    assert isinstance(data["rush_surcharge_bps"], int)
    assert isinstance(data["rush_cutoff_hour_utc"], int)
    assert isinstance(data["standard_turnaround_days"], int)
    assert isinstance(data["rush_turnaround_days"], int)
    assert isinstance(data["daily_unit_capacity"], int)


def assert_product(data: dict):
    _assert_common_fields(data)
    assert data["category"] in ("COPIES", "BANNER", "BINDING")
    assert isinstance(data["base_unit_price_cents"], int)
    assert isinstance(data["unit_size"], int) and data["unit_size"] >= 1
    assert isinstance(data["requires_proof"], bool)
    assert isinstance(data["requires_press"], bool)
    assert isinstance(data["active"], bool)


def assert_pricing_tier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["min_quantity"], int) and data["min_quantity"] >= 1
    assert isinstance(data["discount_bps"], int)


def assert_finishing_option(data: dict):
    _assert_common_fields(data)
    assert data["surcharge_kind"] in ("PER_UNIT", "FLAT")
    assert isinstance(data["surcharge_cents"], int) and data["surcharge_cents"] >= 0


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["completed_order_count"], int)
    assert isinstance(data["lifetime_paid_cents"], int)
    assert isinstance(data["loyalty_score"], (int, float))
    assert data["loyalty_tier"] in ("NONE", "SILVER", "GOLD")


def assert_order(data: dict):
    _assert_common_fields(data)
    assert data["production_status"] in (
        "DRAFT", "CONFIRMED", "IN_PRODUCTION", "READY", "FULFILLED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "INVOICED", "PAID", "REFUNDED")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_order_line(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "OPEN", "PREFLIGHT_OK", "PROOF_PENDING", "PROOF_APPROVED", "PRICE_LOCKED", "PRODUCED")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["production_units"], int)
    assert isinstance(data["estimate_line_cents"], int)


def assert_artwork(data: dict):
    _assert_common_fields(data)
    assert data["preflight_status"] in ("UPLOADED", "PASSED", "FAILED")
    assert isinstance(data["page_count"], int)
    assert isinstance(data["dpi"], int)


def assert_proof(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "CHANGES_REQUESTED")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1


def assert_fulfillment(data: dict):
    _assert_common_fields(data)
    assert data["method"] in ("PICKUP", "SHIP")
    assert data["status"] in ("SCHEDULED", "HANDED_OFF")
    assert isinstance(data["ship_fee_cents"], int)


def assert_press(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cleanup_buffer_minutes"], int)


def assert_press_booking(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("CONFIRMED", "RELEASED")


def assert_capacity_reservation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("HELD", "RELEASED")
    assert isinstance(data["units"], int)
