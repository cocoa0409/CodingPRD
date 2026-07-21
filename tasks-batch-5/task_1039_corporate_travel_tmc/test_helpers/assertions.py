"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common server-managed fields carried by every top-level resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and only increases"


def assert_travel_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["max_air_class"] in ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST")
    for f in ("max_hotel_nightly_cents", "advance_purchase_days",
              "requires_manager_approval_over_cents", "requires_exec_approval_over_cents",
              "exchange_penalty_cents", "credit_validity_days"):
        assert isinstance(data[f], int), f"{f} must be integer cents/count"


def assert_traveler(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["grade"] in ("STANDARD", "MANAGER", "EXECUTIVE", "VIP")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_vendor(data: dict):
    _assert_common(data)
    assert data["vendor_type"] in ("AIR", "HOTEL", "CAR")
    assert isinstance(data["is_preferred"], bool)
    assert isinstance(data["capacity"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_negotiated_rate(data: dict):
    _assert_common(data)
    assert isinstance(data["negotiated_fare_cents"], int)
    assert isinstance(data["market_fare_cents"], int)
    assert isinstance(data["cap_usage_count"], int)
    assert isinstance(data["consumed_count"], int) and data["consumed_count"] >= 0
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED")


def assert_trip_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PENDING_MANAGER", "PENDING_EXEC",
                              "APPROVED", "BOOKED", "CANCELLED")
    assert data["approval_level_required"] in ("NONE", "MANAGER", "EXEC")
    assert isinstance(data["actual_cost_cents"], int)


def assert_booking(data: dict):
    _assert_common(data)
    assert data["segment_type"] in ("AIR", "HOTEL", "CAR")
    assert data["fare_basis"] in ("REFUNDABLE", "NONREFUNDABLE")
    assert isinstance(data["fare_cents"], int)
    assert isinstance(data["credit_applied_cents"], int) and data["credit_applied_cents"] >= 0
    assert isinstance(data["exchange_fee_cents"], int) and data["exchange_fee_cents"] >= 0
    assert data["status"] in ("TICKETED", "EXCHANGED", "CANCELLED", "REFUNDED")


def assert_group_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["block_size"], int) and data["block_size"] >= 1
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0
    assert data["status"] in ("HELD", "CONFIRMED", "RELEASED", "CANCELLED")


def assert_unused_ticket_credit(data: dict):
    _assert_common(data)
    assert isinstance(data["face_value_cents"], int)
    assert isinstance(data["residual_value_cents"], int) and data["residual_value_cents"] >= 0
    assert data["status"] in ("AVAILABLE", "PARTIALLY_USED", "REDEEMED", "EXPIRED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["invoiced_total_cents"], int)
    assert isinstance(data["reconciled_total_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert data["status"] in ("RECEIVED", "RECONCILED", "DISPUTED", "PAID")


def assert_invoice_line(data: dict):
    _assert_common(data)
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["matched_amount_cents"], int)
    assert data["match_status"] in ("MATCHED", "PRICE_VARIANCE", "UNMATCHED")


def assert_credit_value_conserved(credit: dict, applied_total: int):
    """PRD §3.5: face_value always equals residual plus applied-to-date."""
    assert credit["face_value_cents"] == credit["residual_value_cents"] + applied_total, (
        f"value not conserved: face {credit['face_value_cents']} != "
        f"residual {credit['residual_value_cents']} + applied {applied_total}"
    )
