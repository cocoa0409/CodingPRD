"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_mutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def _common_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "append-only record must not carry updated_at"
    assert "version" not in data or data.get("version") is None, \
        "append-only record must not carry version"


def assert_defendant(data: dict):
    _common_mutable(data)
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert isinstance(data["full_name"], str)
    assert data["supervision_status"] in (
        "PRETRIAL_PENDING", "ACTIVE", "DISCHARGED", "TERMINATED")
    assert data["supervision_level"] in (None, "MINIMUM", "MEDIUM", "MAXIMUM")
    assert data["risk_tier"] in (None, "LOW", "MODERATE", "HIGH")
    assert isinstance(data["indigent"], bool)
    assert isinstance(data["cumulative_violation_score"], int)
    assert isinstance(data["balance_owed_cents"], int)


def assert_assessment(data: dict):
    _common_mutable(data)
    assert data["instrument_type"] in ("SCREENING", "FULL")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert data["recommended_level"] in (None, "MINIMUM", "MEDIUM", "MAXIMUM")


def assert_release_order(data: dict):
    _common_mutable(data)
    assert data["decision"] in ("RELEASE", "DETAIN")
    assert data["status"] in ("PROPOSED", "ORDERED", "DENIED", "VACATED")
    assert isinstance(data["ordered_conditions"], list)


def assert_check_in(data: dict):
    _common_mutable(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "MISSED")
    assert data["origin"] in ("MANUAL", "ESCALATION")


def assert_em_device(data: dict):
    _common_mutable(data)
    assert isinstance(data["total_units"], int)
    assert isinstance(data["available_units"], int)
    assert data["available_units"] <= data["total_units"]


def assert_em_enrollment(data: dict):
    _common_mutable(data)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")


def assert_violation(data: dict):
    _common_mutable(data)
    assert data["violation_type"] in (
        "CURFEW", "MISSED_CHECK_IN", "POSITIVE_TEST", "FTA", "NEW_ARREST", "OTHER")
    assert data["severity"] in ("MINOR", "MODERATE", "MAJOR")
    assert data["status"] in (
        "REPORTED", "UNDER_REVIEW", "ADJUDICATED_SANCTION", "ADJUDICATED_DISMISS")
    assert isinstance(data["severity_points"], int)


def assert_court_event(data: dict):
    _common_mutable(data)
    assert data["status"] in ("SCHEDULED", "APPEARED", "FTA", "CONTINUED")


def assert_drug_test(data: dict):
    _common_mutable(data)
    assert data["test_kind"] in ("DRUG", "ALCOHOL")
    assert data["status"] in (
        "SCHEDULED", "COLLECTED", "RESULT_POSITIVE", "RESULT_NEGATIVE", "MISSED")


def assert_testing_site(data: dict):
    _common_mutable(data)
    assert isinstance(data["slot_capacity"], int) and data["slot_capacity"] >= 1


def assert_curfew_window(data: dict):
    _common_append_only(data)
    assert 0 <= data["day_of_week"] <= 6
    assert 0 <= data["start_minute"] <= 1439
    assert data["end_minute"] > data["start_minute"]


def assert_location_ping(data: dict):
    _common_append_only(data)
    assert isinstance(data["at_home"], bool)
    assert isinstance(data["is_curfew_violation"], bool)


def assert_ledger_entry(data: dict):
    _common_append_only(data)
    assert data["entry_type"] in ("CHARGE", "PAYMENT", "WAIVER", "REVERSAL")
    assert isinstance(data["amount_cents"], int)
    assert data["source"] in ("SUPERVISION_FEE", "MANUAL")


def assert_level_adjustment(data: dict):
    _common_append_only(data)
    assert data["to_level"] in ("MINIMUM", "MEDIUM", "MAXIMUM")
    assert data["source"] in ("MANUAL", "AUTO_ESCALATION")
