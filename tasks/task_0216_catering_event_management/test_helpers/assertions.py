"""Entity assertions and domain invariant checkers for the Catering Event Management API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id (UUID, no prefix), created_at/updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["billing_email"], str)
    assert isinstance(data["tax_exempt"], bool)
    assert data["gratuity_policy"] in ("INCLUDED", "OPTIONAL")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_package(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["per_head_cents"], int) and data["per_head_cents"] >= 0
    assert isinstance(data["min_headcount"], int) and data["min_headcount"] >= 1
    assert isinstance(data["lead_time_hours"], int) and data["lead_time_hours"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_venue(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["tax_rate_bps"], int) and 0 <= data["tax_rate_bps"] <= 2000
    assert isinstance(data["service_fee_bps"], int) and 0 <= data["service_fee_bps"] <= 5000
    assert isinstance(data["max_overlapping_events"], int) and data["max_overlapping_events"] >= 1


def assert_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vehicle_capacity_legs"], int) and data["vehicle_capacity_legs"] >= 1
    assert data["posture"] in ("OPEN", "ROLLING", "CLOSED", "BLOCKED")
    assert isinstance(data["dispatched_leg_count"], int) and data["dispatched_leg_count"] >= 0


def assert_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert is_valid_uuid(data.get("package_id", "")), "package_id must be a UUID"
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be a UUID"
    assert isinstance(data["booked_headcount"], int) and data["booked_headcount"] >= 1
    assert data["lifecycle_status"] in (
        "DRAFT", "CONFIRMED", "GUARANTEED", "FULFILLED", "CANCELLED",
    )
    assert data["settlement_status"] in (
        "UNBILLED", "DEPOSIT_HELD", "INVOICED", "SETTLED", "REFUNDED", "FORFEITED",
    )


def assert_add_on(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert data["kind"] in ("DELIVERY", "SETUP", "STAFFING")
    assert isinstance(data["unit_cents"], int) and data["unit_cents"] >= 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_delivery_leg(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("route_id", "")), "route_id must be a UUID"
    assert data["stop_status"] in ("PLANNED", "DISPATCHED", "DELIVERED", "FAILED")


def assert_change_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert isinstance(data["requested_headcount"], int)
    assert data["status"] in ("PROPOSED", "COUNTERED", "ACCEPTED", "REJECTED")


def assert_staffing_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert isinstance(data["reserved_staff"], int) and data["reserved_staff"] >= 0
    assert data["status"] in ("HELD", "RELEASED")


def assert_ledger_entry(data: dict):
    """DepositLedgerEntry is append-only: id + created_at only, NO updated_at, NO version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "ledger id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "ledger created_at must be ISO 8601"
    assert data["entry_type"] in (
        "DEPOSIT_HOLD", "DEPOSIT_APPLY", "REFUND", "FORFEIT", "CHANGE_FEE_DEBIT",
    )
    assert isinstance(data["amount_cents"], int)


def ledger_balance(entries: list) -> int:
    """Running deposit balance: sum of amount_cents over entries (PRD §2.8)."""
    return sum(int(e["amount_cents"]) for e in entries)
