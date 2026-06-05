"""Entity assertions and domain invariant checkers for the SNF-MDS API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ResidentStatus,
    PasrrStatus,
    AdmissionStatus,
    AssessmentStatus,
    CarePlanStatus,
    CarePlanGoalStatus,
    BedHoldStatus,
    ClaimStatus,
)


def _assert_common_fields(data: dict) -> None:
    """Mutable entities carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_facility(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["cms_certification_number"], str) and len(data["cms_certification_number"]) > 0
    assert isinstance(data["certified_bed_count"], int) and data["certified_bed_count"] >= 1
    assert isinstance(data["occupied_bed_count"], int) and data["occupied_bed_count"] >= 0
    assert data["health_inspection_rating"] in range(1, 6)
    assert data["staffing_rating"] in range(1, 6)
    assert data["quality_measure_rating"] in range(1, 6)
    assert data["overall_star_rating"] in range(1, 6)


def assert_pdpm_rate(data: dict) -> None:
    _assert_common_fields(data)
    assert data["component"] in {"PT", "OT", "SLP", "NURSING", "NTA"}
    assert isinstance(data["case_mix_group"], str)
    assert data["case_mix_index"] > 0
    assert isinstance(data["base_rate_cents"], int) and data["base_rate_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_resident(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["medical_record_number"], str) and len(data["medical_record_number"]) > 0
    assert isinstance(data["primary_facility_id"], str)
    assert data["status"] in {s.value for s in ResidentStatus}


def assert_pasrr_screening(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["resident_id"], str)
    assert data["level"] in {"LEVEL_I", "LEVEL_II"}
    assert isinstance(data["has_serious_mental_illness_indicator"], bool)
    assert data["status"] in {s.value for s in PasrrStatus}


def assert_qualifying_stay(data: dict) -> None:
    """QualifyingStay is append-only (PRD §2.4): id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["midnights_count"], int) and data["midnights_count"] >= 0
    assert isinstance(data["qualifies"], bool)


def assert_admission(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["pasrr_screening_id"], str)
    assert data["payer_source"] in {"MEDICARE_A", "MEDICAID", "PRIVATE", "MANAGED_CARE"}
    assert isinstance(data["medicare_covered"], bool)
    assert isinstance(data["covered_day_count"], int)
    assert data["status"] in {s.value for s in AdmissionStatus}


def assert_mds_assessment(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["admission_id"], str)
    assert data["assessment_type"] in {"ADMISSION_5DAY", "INTERIM_IPA", "DISCHARGE"}
    assert 0 <= data["pt_function_score"] <= 24
    assert 0 <= data["slp_components_count"] <= 3
    assert 0 <= data["nta_comorbidity_points"] <= 20
    assert data["status"] in {s.value for s in AssessmentStatus}


def assert_therapy_log(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["admission_id"], str)
    assert data["discipline"] in {"PT", "OT", "SLP"}
    assert data["mode"] in {"INDIVIDUAL", "CONCURRENT", "GROUP"}
    assert isinstance(data["minutes"], int) and data["minutes"] >= 1
    assert isinstance(data["individual_equivalent_minutes"], int)


def assert_care_plan(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["admission_id"], str)
    assert isinstance(data["review_interval_days"], int) and data["review_interval_days"] >= 1
    assert isinstance(data["open_goal_count"], int) and data["open_goal_count"] >= 0
    assert data["status"] in {s.value for s in CarePlanStatus}


def assert_care_plan_goal(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["care_plan_id"], str)
    assert isinstance(data["description"], str)
    assert data["status"] in {s.value for s in CarePlanGoalStatus}


def assert_bed_hold(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["admission_id"], str)
    assert data["leave_reason"] in {"HOSPITAL", "THERAPEUTIC", "OTHER"}
    assert isinstance(data["leave_day_count"], int)
    assert isinstance(data["paid_day_count"], int)
    assert data["status"] in {s.value for s in BedHoldStatus}


def assert_claim(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["admission_id"], str)
    assert isinstance(data["driving_assessment_id"], str)
    assert isinstance(data["billed_day_count"], int)
    assert isinstance(data["estimated_amount_cents"], int)
    assert isinstance(data["final_amount_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert data["status"] in {s.value for s in ClaimStatus}


def assert_quality_measure(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["facility_id"], str)
    assert data["measure_code"] in {
        "FALLS_WITH_INJURY", "PRESSURE_ULCER", "ANTIPSYCHOTIC_USE", "REHOSPITALIZATION"
    }
    assert isinstance(data["numerator"], int) and data["numerator"] >= 0
    assert isinstance(data["denominator"], int) and data["denominator"] >= 1
    assert 1 <= data["measure_points"] <= 100
