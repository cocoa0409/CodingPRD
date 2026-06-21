"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def _assert_append_only(data: dict):
    """Append-only audit records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_employer_program(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["employer_name"], str) and len(data["employer_name"]) > 0
    assert data["status"] in ("ACTIVE", "FROZEN")
    assert isinstance(data["subsidy_consumed_cents"], int)
    assert isinstance(data["subsidy_budget_cents"], int)


def assert_member(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["can_drive"], bool)
    assert isinstance(data["wallet_balance_cents"], int) and data["wallet_balance_cents"] >= 0
    assert isinstance(data["reliability_score"], (int, float))
    assert 0.0 <= float(data["reliability_score"]) <= 100.0


def assert_vehicle(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["hov_eligible"], bool)


def assert_pool(data: dict):
    _assert_common_versioned(data)
    assert data["kind"] in ("CARPOOL", "VANPOOL")
    assert data["status"] in ("FORMING", "ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["seat_capacity"], int)
    assert isinstance(data["committed_seat_count"], int) and data["committed_seat_count"] >= 0
    assert data["committed_seat_count"] <= data["seat_capacity"]


def assert_match_request(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("OPEN", "MATCHED", "CONFIRMED", "EXPIRED", "CANCELLED")


def assert_membership(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("ACTIVE", "ENDED")
    assert isinstance(data["recurring_seats"], int) and data["recurring_seats"] >= 1


def assert_trip(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("SCHEDULED", "BOARDING", "IN_TRANSIT", "COMPLETED", "CANCELLED")
    assert isinstance(data["seats_reserved"], int) and data["seats_reserved"] >= 0
    assert isinstance(data["total_cost_cents"], int)


def assert_reservation(data: dict):
    _assert_common_versioned(data)
    assert data["reservation_status"] in (
        "RESERVED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["payment_status"] in ("PENDING", "CHARGED", "SETTLED", "REFUNDED")
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 1


def assert_grh_claim(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "REIMBURSED", "DENIED")
    assert data["reason_code"] in ("ILLNESS", "OVERTIME", "EMERGENCY", "DRIVER_CANCEL")


def assert_subsidy_ledger_entry(data: dict):
    _assert_append_only(data)
    assert data["entry_type"] in ("DEBIT", "CREDIT")
    assert data["reason"] in (
        "RESERVATION_FINALIZED", "RESERVATION_CANCELLED", "TRIP_CANCELLED", "GRH_REIMBURSED")


def assert_reliability_event(data: dict):
    _assert_append_only(data)
    assert data["event_type"] in ("COMPLETION", "NO_SHOW", "LATE_CANCEL", "GRH_OVERUSE")
