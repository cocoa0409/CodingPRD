"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_clinic(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) > 0
    assert isinstance(data["med_review_threshold_mg"], int)
    assert isinstance(data["pill_count_tolerance"], int)
    assert is_iso8601_timestamp(data["current_utc"]) or data["current_utc"].endswith("Z")
    assert isinstance(data["version"], int)


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["dea_number"], str)
    assert data["role_kind"] in ["PRESCRIBER", "COMPLIANCE_OFFICER"]


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in [
        "REFERRED", "INTAKE_SCHEDULED", "INTAKE_COMPLETE", "ACTIVE", "DISCHARGED",
    ]
    assert data["compliance_flag"] in ["NONE", "FLAGGED", "CLEARED"]
    assert isinstance(data["current_daily_med_mg"], (int, float))
    assert isinstance(data["open_uds_count"], int)


def assert_opioid_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "EXPIRED", "REVOKED"]


def assert_pdmp_check(data: dict):
    """PdmpCheck is an immutable audit record: id + created_at only, no updated_at/version."""
    _assert_common(data)
    assert data["outcome"] in ["CLEAR", "CONCERN"]
    assert is_iso8601_timestamp(data["queried_utc"]) or data["queried_utc"].endswith("Z")
    assert "updated_at" not in data, "PdmpCheck must not carry updated_at"
    assert "version" not in data, "PdmpCheck must not carry version"


def assert_treatment_plan(data: dict):
    _assert_common(data)
    assert data["modality"] in ["INJECTION", "RFA", "MEDICATION"]
    assert isinstance(data["requires_procedure"], bool)
    assert isinstance(data["requires_medication"], bool)
    assert data["status"] in [
        "PROPOSED", "ACTIVE", "PROCEDURE_PATH", "MEDICATION_PATH", "COMPLETED", "CANCELLED",
    ]


def assert_fluoroscopy_suite(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["cleanup_buffer_minutes"], int)
    assert isinstance(data["booked_minutes"], int)
    assert data["booked_minutes"] >= 0, "booked_minutes is a conserved non-negative quantity"


def assert_procedure(data: dict):
    _assert_common(data)
    assert data["status"] in ["REQUESTED", "SCHEDULED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["duration_minutes"], int)


def assert_prior_authorization(data: dict):
    _assert_common(data)
    assert data["target_kind"] in ["PROCEDURE", "PRESCRIPTION"]
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED"]
    assert isinstance(data["authorized_units"], int)


def assert_prescription(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROPOSED", "ACTIVE", "TAPERING", "SUSPENDED", "DISCONTINUED"]
    assert isinstance(data["provisional_daily_med_mg"], (int, float))
    assert_cost_precision(data["provisional_daily_med_mg"])


def assert_urine_drug_screen(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SCHEDULED", "COLLECTED", "RESULTED_CONSISTENT", "RESULTED_INCONSISTENT",
    ]
    assert isinstance(data["recollect_count"], int)


def assert_pill_count_audit(data: dict):
    _assert_common(data)
    assert data["result"] in ["CONSISTENT", "INCONSISTENT"]
    assert isinstance(data["counted_pills"], int)
    assert isinstance(data["discrepancy_pills"], (int, float))


def assert_controlled_substance_ledger(data: dict):
    _assert_common(data)
    for field in ("total_active_med_mg", "suspended_med_mg", "discontinued_med_mg"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
        assert data[field] >= 0, f"{field} must be non-negative"


def assert_med_conservation(ledger: dict, expected_total: float):
    """Invariant (PRD 2.9): total_active + suspended + discontinued is invariant across
    prescribe/suspend/discontinue events."""
    s = (
        ledger["total_active_med_mg"]
        + ledger["suspended_med_mg"]
        + ledger["discontinued_med_mg"]
    )
    assert abs(s - expected_total) < 0.01, (
        f"MED conservation invariant broken: total_active+suspended+discontinued="
        f"{s}, expected {expected_total}"
    )
