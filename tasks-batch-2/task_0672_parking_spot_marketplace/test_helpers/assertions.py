"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response shape against the PRD contract.
AccessPass and PayoutLedgerEntry are append-only: id + created_at only, no
updated_at / version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_host(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["display_name"], str)
    assert isinstance(data["platform_fee_bps"], int)
    assert 0 <= data["platform_fee_bps"] <= 5000
    assert isinstance(data["lifetime_payout_cents"], int)


def assert_driver(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["wallet_balance_cents"], int)
    assert data["wallet_balance_cents"] >= 0, "wallet_balance_cents must never be negative"
    assert isinstance(data["violation_points"], int)
    assert isinstance(data["provisional_violation_points"], int)
    assert data["standing_tier"] in ("GOOD", "WATCH", "SUSPENDED")


def assert_spot(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["host_id"], str)
    assert isinstance(data["zone_code"], str)
    assert isinstance(data["base_hourly_cents"], int) and data["base_hourly_cents"] >= 100
    assert isinstance(data["base_daily_cents"], int) and data["base_daily_cents"] >= 500
    assert isinstance(data["monthly_flat_cents"], int) and data["monthly_flat_cents"] >= 5000
    assert data["listing_status"] in ("LISTED", "UNLISTED")


def assert_pricing_event(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["zone_code"], str)
    assert isinstance(data["surge_multiplier_bps"], int)
    assert 10000 <= data["surge_multiplier_bps"] <= 50000
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_booking(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["spot_id"], str)
    assert isinstance(data["driver_id"], str)
    assert data["rate_kind"] in ("HOURLY", "DAILY", "MONTHLY")
    assert isinstance(data["quoted_amount_cents"], int)
    assert data["occupancy_status"] in (
        "RESERVED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED", "NO_SHOW")
    assert data["settlement_status"] in ("UNSETTLED", "SETTLED", "REFUNDED")
    assert isinstance(data["transfer_count"], int)


def assert_violation_record(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["driver_id"], str)
    assert data["violation_kind"] in ("OVERSTAY", "UNAUTHORIZED_GATE", "NO_SHOW")
    assert isinstance(data["base_points"], int)
    assert data["status"] in ("OPEN", "CONFIRMED", "DISMISSED")


def assert_transfer_offer(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["from_driver_id"], str)
    assert isinstance(data["to_driver_id"], str)
    assert data["status"] in ("PENDING", "ACCEPTED", "DECLINED", "WITHDRAWN")


def assert_access_pass(data: dict):
    """AccessPass is append-only: id + created_at, no updated_at / version (PRD §2.4)."""
    _assert_append_only(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["qr_token"], str)
    assert isinstance(data["gate_opens_remaining"], int)
    assert data["gate_opens_remaining"] >= 0


def assert_payout_ledger_entry(data: dict):
    """PayoutLedgerEntry is append-only: id + created_at, no updated_at / version (PRD §2.4)."""
    _assert_append_only(data)
    assert isinstance(data["host_id"], str)
    assert isinstance(data["booking_id"], str)
    assert data["entry_type"] in ("EARNING", "REVERSAL")
    assert isinstance(data["amount_cents"], int)
