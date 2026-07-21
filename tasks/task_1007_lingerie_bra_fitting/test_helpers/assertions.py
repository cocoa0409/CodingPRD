"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response structure against the PRD contract
using the framework's generic UUID / timestamp helpers.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["loyalty_points"], int)
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["store_credit_cents"], int) and data["store_credit_cents"] >= 0


def assert_fitter(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["post_surgical_certified"], bool)
    assert isinstance(data["is_active"], bool)


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["room_name"], str) and data["room_name"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["is_private"], bool)
    assert isinstance(data["is_active"], bool)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["fitting_type"] in ("STANDARD", "POST_SURGICAL", "MASTECTOMY")
    assert data["status"] in ("REQUESTED", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED")


def assert_product(data: dict):
    _assert_common(data)
    assert data["category"] in ("EVERYDAY_BRA", "SPORTS_BRA", "MASTECTOMY_BRA", "LINGERIE_SET")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["is_mastectomy"], bool)


def assert_sku(data: dict):
    _assert_common(data)
    assert isinstance(data["band_size"], int)
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["stock_on_hand"], int)
    assert isinstance(data["reserved_count"], int)
    assert isinstance(data["available_units"], int)
    assert data["stock_status"] in ("IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK")
    assert data["available_units"] == data["stock_on_hand"] - data["reserved_count"], \
        "available_units must equal stock_on_hand - reserved_count"


def assert_order(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("DRAFT", "PLACED", "FULFILLED", "CANCELLED")


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("ACTIVE", "CANCELLED", "FULFILLED", "EXCHANGED")


def assert_exchange(data: dict):
    _assert_common(data)
    assert data["item_condition"] in ("SEALED", "TRIED_ON", "WORN")
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED")


def assert_insurance_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "REIMBURSED")
    assert data["decision"] in ("PENDING", "APPROVE", "DENY")


def assert_reminder(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "SENT", "DISMISSED", "CANCELLED")


def assert_loyalty_event(data: dict):
    # Append-only ledger row: id + created_at only (no updated_at / version).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["points_delta"], int)
