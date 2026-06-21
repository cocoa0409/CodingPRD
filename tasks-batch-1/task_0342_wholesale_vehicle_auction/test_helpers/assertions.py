"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_sale(data: dict):
    _assert_common(data)
    assert isinstance(data["sale_name"], str) and len(data["sale_name"]) > 0
    assert isinstance(data["sale_date"], str)
    assert data["buyer_fee_schedule_code"] in ("STANDARD", "PREMIUM")
    assert data["status"] in ("DRAFT", "OPEN", "RUNNING", "CLOSED", "SETTLED")
    assert isinstance(data["lane_count"], int) and data["lane_count"] >= 0


def assert_lane(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sale_id"])
    assert isinstance(data["lane_number"], int) and data["lane_number"] > 0
    assert isinstance(data["open_minute"], int) and data["open_minute"] >= 0
    assert isinstance(data["close_minute"], int) and data["close_minute"] > data["open_minute"]
    assert isinstance(data["scheduled_slot_count"], int) and data["scheduled_slot_count"] >= 0
    assert data["status"] in ("PLANNED", "ACTIVE", "CLOSED", "ARCHIVED")


def assert_seller(data: dict):
    _assert_common(data)
    assert isinstance(data["dealer_name"], str) and len(data["dealer_name"]) > 0
    assert 0 <= data["seller_fee_pct"] <= 0.10
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_buyer(data: dict):
    _assert_common(data)
    assert isinstance(data["dealer_name"], str) and len(data["dealer_name"]) > 0
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["available_credit_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert_buyer_credit_invariant(data)


def assert_buyer_credit_invariant(data: dict):
    """PRD §2.10: available_credit_cents + committed_cents == credit_limit_cents at all times."""
    assert data["available_credit_cents"] + data["committed_cents"] == data["credit_limit_cents"], (
        f"credit conservation violated: available {data['available_credit_cents']} + "
        f"committed {data['committed_cents']} != limit {data['credit_limit_cents']}"
    )


def assert_consignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sale_id"])
    assert is_valid_uuid(data["seller_id"])
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17
    assert isinstance(data["reserve_price_cents"], int) and data["reserve_price_cents"] >= 0
    assert isinstance(data["floor_price_cents"], int) and data["floor_price_cents"] >= 0
    assert data["title_status"] in ("ABSENT", "ON_HAND")
    assert isinstance(data["expected_proceeds_cents"], int)
    assert data["status"] in (
        "SUBMITTED", "CATALOGED", "RUN_LISTED", "SOLD", "NO_SALE",
        "IF_PENDING", "SETTLED", "ARB_UNWOUND", "WITHDRAWN",
    )


def assert_condition_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["consignment_id"])
    assert 0.0 <= data["grade"] <= 5.0
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0
    assert isinstance(data["announcements"], list)
    assert isinstance(data["as_is"], bool)


def assert_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sale_id"])
    assert is_valid_uuid(data["consignment_id"])
    assert is_valid_uuid(data["lane_id"])
    assert isinstance(data["run_number"], int) and data["run_number"] > 0
    assert isinstance(data["slot_start_minute"], int)
    assert isinstance(data["slot_end_minute"], int) and data["slot_end_minute"] > data["slot_start_minute"]
    assert isinstance(data["starting_bid_cents"], int) and data["starting_bid_cents"] >= 0
    assert isinstance(data["high_bid_cents"], int)
    assert data["high_bidder_id"] is None or is_valid_uuid(data["high_bidder_id"])
    assert isinstance(data["hammer_price_cents"], int)
    assert data["outcome"] in ("NONE", "SOLD", "IF", "PASSED")
    assert data["status"] in (
        "SCHEDULED", "BIDDING_OPEN", "BIDDING_CLOSED", "HAMMERED",
        "PASSED", "IF_PENDING", "FINALIZED", "ARB_REVERSED", "WITHDRAWN",
    )


def assert_bid(data: dict):
    """Bid is append-only: only id + created_at + its own fields; no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Bid is append-only and must NOT carry updated_at"
    assert "version" not in data, "Bid is append-only and must NOT carry version"
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["buyer_id"])
    assert data["bid_type"] in ("LIVE", "PROXY")
    assert data["channel"] in ("LANE", "ONLINE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["ceiling_cents"], int)


def assert_arbitration_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["buyer_id"])
    assert data["reason_code"] in ("UNDISCLOSED_DAMAGE", "TITLE_DISCREPANCY", "MECHANICAL")
    assert isinstance(data["claimed_cents"], int) and data["claimed_cents"] > 0
    assert isinstance(data["approved_cents"], int) and data["approved_cents"] >= 0
    assert data["resolution"] in ("PENDING", "APPROVED_FULL", "APPROVED_PARTIAL", "DENIED")
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["buyer_id"])
    assert is_valid_uuid(data["seller_id"])
    assert isinstance(data["sale_price_cents"], int)
    assert isinstance(data["buyer_fee_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["seller_proceeds_cents"], int)
    assert data["payment_status"] in ("UNPAID", "PAID", "REVERSED", "WRITTEN_OFF")
    assert data["title_status"] in ("PENDING_TITLE", "TITLE_RECEIVED")
    assert data["status"] in ("OPEN", "CLEARED", "VOID", "DEFAULTED")


def assert_gate_pass(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["settlement_id"])
    assert is_valid_uuid(data["buyer_id"])
    assert data["status"] in ("ISSUED", "REDEEMED", "VOID")


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data["carrier_name"], str) and len(data["carrier_name"]) > 0
    assert isinstance(data["turnaround_buffer_minutes"], int) and data["turnaround_buffer_minutes"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_transport_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["settlement_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert isinstance(data["pickup_start_minute"], int) and data["pickup_start_minute"] >= 0
    assert isinstance(data["pickup_end_minute"], int) and data["pickup_end_minute"] > data["pickup_start_minute"]
    assert data["status"] in ("REQUESTED", "DISPATCHED", "DELIVERED", "CANCELLED")
