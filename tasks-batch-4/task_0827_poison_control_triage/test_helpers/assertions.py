"""Entity assertions and domain invariant checkers.

Uses the framework generics for UUID / timestamp shape checks.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_CASE_STATUSES = ["INTAKE", "TRIAGED", "MONITORING", "REFERRED", "RETRIAGE", "RESOLVED", "CLOSED"]
_SEVERITY_BANDS = ["MINIMAL", "MODERATE", "SEVERE", "CRITICAL"]
_ASSESSMENT_STATUSES = ["COMPLETED", "FINALIZED", "SUPERSEDED"]
_FOLLOWUP_STATUSES = ["SCHEDULED", "ATTEMPTED", "COMPLETED", "CANCELLED"]
_CONSULT_STATUSES = ["ACTIVE", "CLOSED", "CANCELLED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_substance(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in [
        "ANALGESIC", "HOUSEHOLD_CHEMICAL", "PESTICIDE", "PLANT",
        "PHARMACEUTICAL", "HYDROCARBON", "HEAVY_METAL",
    ]
    assert data["toxic_dose_mg_per_kg"] > 0
    assert data["onset_hours"] > 0
    assert isinstance(data["aggregate_case_count"], int)


def assert_facility(data: dict):
    _assert_common(data)
    assert data["facility_type"] in ["ED", "URGENT_CARE", "ICU", "CLINIC"]
    assert data["status"] in ["ACCEPTING", "DIVERTING", "OFFLINE"]
    assert data["consult_capacity"] >= 1
    assert data["active_consult_count"] >= 0


def assert_specialist(data: dict):
    _assert_common(data)
    assert data["credential"] in ["SPI", "TOXICOLOGIST"]


def assert_exposure_case(data: dict):
    _assert_common(data)
    assert data["status"] in _CASE_STATUSES
    assert data["patient_weight_kg"] > 0
    assert data["patient_age_years"] >= 0
    assert data["patient_sex"] in ["MALE", "FEMALE", "UNKNOWN"]
    assert data["risk_tier"] in _SEVERITY_BANDS or data["risk_tier"] is None
    assert isinstance(data["pending_followup_count"], int)


def assert_exposure(data: dict):
    _assert_common(data)
    assert data["route"] in ["INGESTION", "INHALATION", "DERMAL", "OCULAR", "INJECTION"]
    assert data["dose_range_high_mg"] >= data["dose_range_low_mg"]
    assert data["severity_band"] in _SEVERITY_BANDS
    assert isinstance(data["toxicity_score"], (int, float))


def assert_risk_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in _ASSESSMENT_STATUSES
    assert data["risk_tier"] in _SEVERITY_BANDS
    assert isinstance(data["aggregate_score_max"], (int, float))
    assert isinstance(data["aggregate_score_additive"], (int, float))


def assert_disposition(data: dict):
    _assert_common(data)
    assert data["disposition_type"] in ["HOME_MANAGEMENT", "ED_REFERRAL"]
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_follow_up_call(data: dict):
    _assert_common(data)
    assert data["status"] in _FOLLOWUP_STATUSES
    assert data["sequence_index"] >= 0
    assert isinstance(data["attempt_count"], int)


def assert_facility_consult(data: dict):
    _assert_common(data)
    assert data["status"] in _CONSULT_STATUSES
    assert isinstance(data["billing_units"], (int, float))


def assert_npds_report(data: dict):
    _assert_common(data)
    assert data["report_status"] in ["SUBMITTED", "RETRACTED"]
    assert data["medical_outcome"] in ["MINOR", "MODERATE", "MAJOR"]


def assert_case_note(data: dict):
    """CaseNote is append-only: it has id + created_at but NO updated_at/version."""
    _assert_common(data)
    assert data["note_type"] in ["INTAKE", "CLINICAL", "INTERPRETER", "DISPOSITION", "FOLLOWUP"]
    assert "updated_at" not in data, "CaseNote must not carry updated_at"
    assert "version" not in data, "CaseNote must not carry version"
