"""Entity assertions and domain invariant checkers for the Blood Donation Center API.

Every entity in this domain carries the full common-field quartet
(id, created_at, updated_at, version) per PRD §2.4.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

BLOOD_TYPES = ["O_NEG", "O_POS", "A_NEG", "A_POS", "B_NEG", "B_POS", "AB_NEG", "AB_POS", "UNKNOWN"]
COMPONENTS = ["RBC", "PLASMA", "PLATELET", "WHOLE_BLOOD"]


def _assert_common(data: dict):
    """The id/created_at/updated_at/version quartet every entity carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_center(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region_code"], str)
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"


def assert_donor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["blood_type"] in BLOOD_TYPES
    assert data["eligibility_status"] in ["ELIGIBLE", "TEMP_DEFERRED", "PERM_DEFERRED", "UNDERAGE"]
    assert data["pending_donation_type"] in ["WHOLE", "PLASMA", "PLATELET", "NONE"]
    assert isinstance(data["lifetime_collected_count"], int)
    assert data["lifetime_collected_count"] >= 0


def assert_deferral(data: dict):
    _assert_common(data)
    assert data["category"] in ["TRAVEL", "MEDICATION", "HEMOGLOBIN", "ADVERSE_REACTION", "INFECTIOUS_RISK"]
    assert data["kind"] in ["TEMPORARY", "PERMANENT"]
    assert data["status"] in ["ACTIVE", "EXPIRED", "LIFTED"]
    assert is_iso8601_timestamp(data["starts_at"]), "starts_at must be ISO 8601"
    if data["kind"] == "PERMANENT":
        assert data.get("expires_at") is None, "PERMANENT deferral has null expires_at"


def assert_slot(data: dict):
    _assert_common(data)
    assert data["donation_type"] in ["WHOLE", "PLASMA", "PLATELET"]
    assert data["status"] in ["OPEN", "FULL", "CLOSED"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"]
    assert data["donation_type"] in ["WHOLE", "PLASMA", "PLATELET"]
    assert is_valid_uuid(data["donor_id"])
    assert is_valid_uuid(data["slot_id"])


def assert_health_screening(data: dict):
    _assert_common(data)
    assert data["outcome"] in ["PASS", "FAIL"]
    assert data["failure_reason"] in [
        "NONE", "HEMOGLOBIN_LOW", "UNDERWEIGHT", "VITALS_OUT_OF_RANGE", "TRAVEL_RISK", "MEDICATION"
    ]
    assert is_valid_uuid(data["appointment_id"])


def assert_donation(data: dict):
    _assert_common(data)
    assert data["status"] in ["COLLECTED", "RELEASABLE", "DISCARDED"]
    assert data["donation_type"] in ["WHOLE", "PLASMA", "PLATELET"]
    assert isinstance(data["volume_ml"], int) and data["volume_ml"] >= 1
    assert is_iso8601_timestamp(data["collected_at"])


def assert_test_result(data: dict):
    _assert_common(data)
    assert data["panel_outcome"] in ["NEGATIVE", "POSITIVE", "INDETERMINATE"]
    assert is_valid_uuid(data["donation_id"])
    assert is_iso8601_timestamp(data["resulted_at"])


def assert_blood_unit(data: dict):
    _assert_common(data)
    assert data["component"] in COMPONENTS
    assert data["blood_type"] in BLOOD_TYPES
    assert isinstance(data["din"], str) and len(data["din"]) > 0
    assert data["status"] in [
        "QUARANTINED", "AVAILABLE", "RESERVED", "ISSUED", "EXPIRED", "DISCARDED", "RECALLED"
    ]
    assert is_iso8601_timestamp(data["collected_at"])


def assert_adverse_reaction(data: dict):
    _assert_common(data)
    assert data["severity"] in ["MILD", "MODERATE", "SEVERE"]
    assert isinstance(data["symptom"], str) and len(data["symptom"]) >= 3
    assert is_iso8601_timestamp(data["occurred_at"])


def assert_recall_event(data: dict):
    _assert_common(data)
    assert data["reason"] in ["POSITIVE_RETEST", "POST_DONATION_ILLNESS", "TRAVEL_DISCLOSURE", "OTHER"]
    assert data["status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["lookback_days"], int) and data["lookback_days"] >= 1
    assert isinstance(data["units_recalled_count"], int) and data["units_recalled_count"] >= 0
    assert isinstance(data["donations_in_scope_count"], int) and data["donations_in_scope_count"] >= 0


def assert_inventory_bucket(data: dict):
    _assert_common(data)
    assert data["blood_type"] in BLOOD_TYPES
    assert data["component"] in COMPONENTS
    assert isinstance(data["available_count"], int) and data["available_count"] >= 0
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
