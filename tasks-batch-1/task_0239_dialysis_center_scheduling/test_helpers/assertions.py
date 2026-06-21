"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. All field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields every resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_clinic(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("OPEN", "SUSPENDED", "CLOSED")
    assert isinstance(data["dialyzer_reuse_limit"], int)


def assert_shift(data: dict):
    _assert_common(data)
    assert data["day_pattern"] in ("MWF", "TTHS")
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert data["end_minute"] > data["start_minute"]
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_machine(data: dict):
    _assert_common(data)
    assert isinstance(data["asset_tag"], str)
    assert isinstance(data["supports_hdf"], bool)
    assert isinstance(data["dialyzer_reuse_count"], int)
    assert data["dialyzer_reuse_count"] >= 0
    assert data["status"] in ("AVAILABLE", "IN_MAINTENANCE", "RETIRED")


def assert_station(data: dict):
    _assert_common(data)
    assert isinstance(data["chair_label"], str)
    assert isinstance(data["isolation_capable"], bool)
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["mrn"], str)
    assert isinstance(data["full_name"], str)
    assert data["patient_kind"] in ("RESIDENT", "TRANSIENT")
    assert data["payer_class"] in ("CONTRACTED", "STANDARD")
    assert isinstance(data["requires_isolation"], bool)
    assert 0.0 <= data["coinsurance_pct"] <= 1.0
    assert isinstance(data["no_show_count_window"], int)
    assert data["adherence_status"] in ("GOOD_STANDING", "AT_RISK", "SUSPENDED")
    assert isinstance(data["account_balance_cents"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert data["modality"] in ("HEMODIALYSIS", "HEMODIAFILTRATION", "PERITONEAL")
    assert data["status"] in ("DRAFT", "ACTIVE", "UNDER_REVISION", "REVOKED")


def assert_standing_slot(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "RELEASED")


def assert_session(data: dict):
    _assert_common(data)
    assert data["clinical_status"] in (
        "BOOKED", "CHECKED_IN", "COMPLETED", "MISSED", "CANCELLED"
    )
    assert data["billing_status"] in ("UNBILLED", "BILLED", "SETTLED", "VOID")


def assert_lab_order(data: dict):
    _assert_common(data)
    assert data["panel"] in ("MONTHLY_CHEM", "CBC", "IRON_STUDIES")
    assert data["status"] in ("SCHEDULED", "COLLECTED", "CANCELLED")


def assert_transport_trip(data: dict):
    _assert_common(data)
    assert data["direction"] in ("INBOUND", "OUTBOUND")
    assert isinstance(data["fare_cents"], int)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED")


def assert_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["session_count"], int)
    assert isinstance(data["coinsurance_due_cents"], int)
    assert isinstance(data["missed_fee_total_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert data["status"] in ("ISSUED", "PAID", "CANCELLED")
