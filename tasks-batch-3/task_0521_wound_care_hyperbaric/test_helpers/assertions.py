"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    """Entities with common_fields:true carry updated_at + version."""
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_center(data: dict):
    _assert_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data.get("current_utc", "")), "current_utc must be ISO 8601"


def assert_clinician(data: dict):
    _assert_versioned(data)
    assert isinstance(data["center_id"], str)
    assert isinstance(data["name"], str)
    assert data["role_kind"] in ["WOUND", "HYPERBARIC", "ATTENDING"]
    assert isinstance(data["active"], bool)


def assert_chamber(data: dict):
    _assert_versioned(data)
    assert isinstance(data["center_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert data["turnover_buffer_minutes"] >= 0
    assert isinstance(data["occupied_slot_count"], int)
    assert data["occupied_slot_count"] >= 0, "occupied_slot_count must never go negative"


def assert_payer_policy(data: dict):
    _assert_versioned(data)
    assert isinstance(data["center_id"], str)
    assert isinstance(data["payer_name"], str)
    assert isinstance(data["requires_prior_auth"], bool)
    assert data["max_covered_hbo_sessions"] >= 0
    assert data["per_session_cents"] >= 0


def assert_patient(data: dict):
    _assert_versioned(data)
    assert isinstance(data["center_id"], str)
    assert isinstance(data["mrn"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["payer_policy_id"], str)
    assert data["status"] in ["INTAKE", "IN_CARE", "DISCHARGED", "TRANSFERRED"]
    assert data["latest_wound_area_cm2"] >= 0


def assert_referral(data: dict):
    _assert_versioned(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["source_provider"], str)
    assert data["status"] in ["RECEIVED", "NEEDS_INFO", "ACCEPTED", "DECLINED"]


def assert_wound_assessment(data: dict):
    """WoundAssessment is append-only (common_fields:false): id + created_at,
    NO updated_at, NO version."""
    _assert_common(data)
    assert "version" not in data, "append-only WoundAssessment must not carry a version field"
    assert "updated_at" not in data, "append-only WoundAssessment must not carry updated_at"
    assert isinstance(data["patient_id"], str)
    assert is_iso8601_timestamp(data.get("assessed_at", "")), "assessed_at must be ISO 8601"
    assert data["stage"] in ["STAGE_1", "STAGE_2", "STAGE_3", "STAGE_4", "UNSTAGEABLE"]
    assert data["length_cm"] > 0
    assert data["width_cm"] > 0
    assert data["tissue_type"] in ["GRANULATION", "EPITHELIAL", "SLOUGH", "NECROTIC"]
    assert isinstance(data["infected"], bool)
    assert isinstance(data["area_cm2"], (int, float))
    assert isinstance(data["severity_score"], int)
    assert 1 <= data["severity_score"] <= 100


def assert_photo_document(data: dict):
    """PhotoDocument is append-only (common_fields:false)."""
    _assert_common(data)
    assert "version" not in data, "append-only PhotoDocument must not carry a version field"
    assert "updated_at" not in data, "append-only PhotoDocument must not carry updated_at"
    assert isinstance(data["wound_assessment_id"], str)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["image_uri"], str)
    assert is_iso8601_timestamp(data.get("captured_at", "")), "captured_at must be ISO 8601"


def assert_treatment_plan(data: dict):
    _assert_versioned(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["baseline_assessment_id"], str)
    assert data["coverage_status"] in ["PENDING", "COVERED", "NOT_COVERED"]
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "HEALED", "CLOSED"]
    assert isinstance(data["provisional_covered_cents"], int)
    assert isinstance(data["provisional_hbo_covered_cents"], int)
    assert isinstance(data["finalized_hbo_covered_cents"], int)
    assert data["debridement_supply_budget_cents"] >= 0


def assert_prior_authorization(data: dict):
    _assert_versioned(data)
    assert isinstance(data["treatment_plan_id"], str)
    assert data["requested_hbo_sessions"] >= 1
    assert data["status"] in ["SUBMITTED", "ADDITIONAL_INFO_REQUESTED", "APPROVED", "DENIED"]


def assert_debridement_procedure(data: dict):
    _assert_versioned(data)
    assert isinstance(data["treatment_plan_id"], str)
    assert isinstance(data["clinician_id"], str)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_hbo_session(data: dict):
    _assert_versioned(data)
    assert isinstance(data["treatment_plan_id"], str)
    assert isinstance(data["chamber_id"], str)
    assert data["treatment_pressure_ata"] > 1.0
    assert isinstance(data["dive_log_entries"], list)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_supply_order(data: dict):
    _assert_versioned(data)
    assert isinstance(data["treatment_plan_id"], str)
    assert data["supply_kind"] in ["ADVANCED_DRESSING", "SKIN_GRAFT"]
    assert isinstance(data["line_items"], list)
    assert isinstance(data["covered_cents"], int)
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "CANCELLED"]


def assert_acute_transfer(data: dict):
    _assert_versioned(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["destination_facility"], str)
    assert data["status"] in ["INITIATED", "ACCEPTED", "CANCELLED"]


def assert_outcome_report(data: dict):
    _assert_versioned(data)
    assert isinstance(data["treatment_plan_id"], str)
    assert data["status"] == "FINAL"
    assert isinstance(data["finalized_hbo_covered_cents"], int)
    assert isinstance(data["meets_coverage_threshold"], bool)
