"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_member(data: dict):
    _assert_common(data)
    assert data["membership_tier"] in ("BASIC", "PREMIER")
    assert data["membership_status"] in ("PENDING", "ACTIVE", "LAPSED", "CLOSED")
    assert isinstance(data["join_fee_cents"], int)
    assert isinstance(data["loyalty_points_balance"], int)
    assert isinstance(data["eligible_spend_cents"], int)
    assert isinstance(data["wallet_credit_cents"], int)


def assert_product(data: dict):
    _assert_common(data)
    assert data["category"] in ("TENT", "SLEEPING", "COOKING", "APPAREL", "CLIMBING", "PADDLE")
    assert isinstance(data["retail_price_cents"], int)


def assert_rental_unit(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "RENTED_OUT", "OUT_OF_SERVICE")
    assert data["condition"] in ("GOOD", "DAMAGED")


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "PICKED_UP", "RETURNED", "DAMAGE_ASSESSED", "CLOSED", "CANCELLED")
    assert isinstance(data["rental_days"], int) and data["rental_days"] >= 1
    assert isinstance(data["rental_fee_cents"], int)


def assert_trip(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "OPEN", "DEPARTED", "COMPLETED", "CANCELLED")
    assert isinstance(data["seats_confirmed"], int)


def assert_guide(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_trip_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED")


def assert_trade_in(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "OFFERED", "COUNTERED", "ACCEPTED", "REJECTED")


def assert_repair_order(data: dict):
    _assert_common(data)
    assert data["repair_stage"] in ("RECEIVED", "DIAGNOSED", "IN_REPAIR", "READY", "PICKED_UP")
    assert data["billing_stage"] in ("UNBILLED", "INVOICED", "SETTLED")
    assert data["warranty_status"] in ("UNDETERMINED", "COVERED", "DENIED")


def assert_pass(data: dict):
    _assert_common(data)
    assert data["coverage_status"] in ("PENDING", "ACTIVE", "EXPIRED", "VOID")


def assert_special_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "QUOTED", "CONFIRMED", "FULFILLED", "CANCELLED")


def assert_purchase(data: dict):
    _assert_common(data)
    assert data["status"] in ("COMPLETED", "REFUNDED")


def assert_declaration(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED")


def assert_loyalty_balance_conserved(member: dict, ledger_entries: list):
    """§2.8: a member's loyalty_points_balance equals the sum of its ledger deltas."""
    total = sum(e["delta"] for e in ledger_entries)
    assert member["loyalty_points_balance"] == total, (
        f"loyalty_points_balance {member['loyalty_points_balance']} != sum(delta) {total}"
    )
