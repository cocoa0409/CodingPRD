"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version begins at 1"


def assert_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["holder_name"], str) and len(data["holder_name"]) > 0
    assert isinstance(data["home_state_code"], str)
    assert data["status"] in ("ACTIVE", "DELINQUENT", "SUSPENDED", "CLOSED")
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["low_balance_threshold_cents"], int)
    assert data["low_balance_threshold_cents"] >= 0
    assert isinstance(data["auto_reload_enabled"], bool)
    assert data["reload_policy"] in ("FIXED", "RESTORE_TO_TARGET")
    assert isinstance(data["outstanding_fines_cents"], int)
    assert data["outstanding_fines_cents"] >= 0


def assert_vehicle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["plate_number"], str)
    assert isinstance(data["plate_state_code"], str)
    assert data["registration_status"] in ("REGISTERED", "LAPSED")
    assert isinstance(data["hov_capable"], bool)
    assert isinstance(data["axle_count"], int) and data["axle_count"] >= 2


def assert_transponder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["serial"], str)
    assert data["status"] in ("UNBOUND", "BOUND", "DEACTIVATED")


def assert_transponder_binding(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["transponder_id"], str)
    assert isinstance(data["vehicle_id"], str)
    assert data["status"] in ("ACTIVE", "ENDED")


def assert_hov_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["declared_occupants"], int)
    assert data["status"] in ("DECLARED", "REVOKED")


def assert_plaza(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["base_rate_cents"], int) and data["base_rate_cents"] > 0
    assert data["peak_multiplier_bps"] >= 0
    assert data["axle_surcharge_cents"] >= 0
    assert data["hov_min_occupants"] >= 2
    assert data["plate_surcharge_bps"] >= 0


def assert_toll_transaction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plaza_id"], str)
    assert data["read_method"] in ("TRANSPONDER", "PLATE")
    assert data["pricing_status"] in ("PENDING", "PRICED", "EXEMPT", "REPRICED")
    assert data["settlement_status"] in ("UNSETTLED", "SETTLED", "IN_VIOLATION", "WRITTEN_OFF")
    assert isinstance(data["gross_toll_cents"], int)
    assert isinstance(data["toll_cents"], int)
    assert isinstance(data["hov_exempt"], bool)


def assert_violation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["toll_transaction_id"], str)
    assert isinstance(data["toll_due_cents"], int)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["fine_total_cents"], int)
    assert isinstance(data["escalation_tier"], int) and data["escalation_tier"] >= 1
    assert data["settlement_status"] in ("ASSESSED", "CONTESTED", "SETTLED", "DISMISSED")


def assert_interop_agency(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert data["settlement_fee_bps"] >= 0
    assert isinstance(data["active"], bool)


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: id + created_at only, NO version, NO updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entry_type"] in (
        "TOLL_DEBIT", "RELOAD_CREDIT", "VIOLATION_SETTLE", "DISPUTE_REFUND", "INTEROP_DEBIT"
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_after_cents"], int)
