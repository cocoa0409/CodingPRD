"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    """Every persisted entity carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["insurance_payer"], str)
    assert isinstance(data["baseline_epworth_score"], int)
    assert 0 <= data["baseline_epworth_score"] <= 24


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["referring_provider_npi"], str)
    assert data["requested_modality"] in ("IN_LAB_PSG", "HSAT")
    assert isinstance(data["clinical_indication"], str)
    assert isinstance(data["prior_auth_required"], bool)
    assert data["status"] in (
        "SUBMITTED", "PENDING_AUTH", "AUTHORIZED", "DENIED",
        "SCHEDULED", "COMPLETED", "CANCELLED",
    )


def assert_sleep_bed(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bed_label"], str) and len(data["bed_label"]) > 0
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert data["turnover_buffer_minutes"] >= 0
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE")


def assert_study_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["referral_id"], str)
    assert data["modality"] in ("IN_LAB_PSG", "HSAT", "IN_LAB_TITRATION")
    assert data["status"] in (
        "ORDERED", "SCHEDULED", "IN_PROGRESS", "SCORED", "INTERPRETED", "CANCELLED",
    )


def assert_scoring_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["study_order_id"], str)
    assert isinstance(data["scored_by_tech_id"], str)
    assert isinstance(data["ahi_snapshot"], (int, float))
    assert data["severity_snapshot"] in ("NONE", "MILD", "MODERATE", "SEVERE")
    assert data["status"] in ("DRAFT", "FINALIZED", "RETURNED")
    assert isinstance(data["physician_recommends_cpap"], bool)


def assert_dme_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["study_order_id"], str)
    assert data["device_type"] in ("CPAP", "APAP", "BIPAP")
    assert isinstance(data["prescribed_pressure_cmh2o"], (int, float))
    assert data["prescribed_pressure_cmh2o"] > 0
    assert isinstance(data["resupply_cycle_number"], int)
    assert data["resupply_cycle_number"] >= 1
    assert data["status"] in ("DRAFT", "SUBMITTED", "FULFILLED", "CANCELLED")


def assert_compliance_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["dme_order_id"], str)
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert isinstance(data["nights_used_4h_plus"], int)
    assert data["nights_used_4h_plus"] >= 0
    assert isinstance(data["total_usage_minutes"], int)
    assert data["total_usage_minutes"] >= 0
    assert isinstance(data["adherent"], bool)


def assert_follow_up(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["study_order_id"], str)
    assert is_iso8601_timestamp(data["scheduled_for_utc"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
