"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid

from .constants import (
    STANDARD_ADMIT_AT,
    RATE_EFFECTIVE_FROM,
    QUALIFYING_HOSPITAL_ADMIT,
    QUALIFYING_HOSPITAL_DISCHARGE,
)


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def create_facility_payload(**overrides) -> dict:
    """Facility: name, cms_certification_number, certified_bed_count required;
    health_inspection_rating / staffing_rating optional (PRD §3.1)."""
    defaults = {
        "name": "Test SNF",
        "cms_certification_number": f"CCN-{_unique_suffix()}",
        "certified_bed_count": 5,
    }
    defaults.update(overrides)
    return defaults


def create_pdpm_rate_payload(**overrides) -> dict:
    """PdpmRate: component, case_mix_group, case_mix_index, base_rate_cents,
    effective_from required; active optional (PRD §3.1)."""
    defaults = {
        "component": "PT",
        "case_mix_group": "TB",
        "case_mix_index": 1.69,
        "base_rate_cents": 7000,
        "effective_from": RATE_EFFECTIVE_FROM,
    }
    defaults.update(overrides)
    return defaults


def create_resident_payload(facility_id, **overrides) -> dict:
    """Resident: full_name, medical_record_number, date_of_birth,
    primary_facility_id required (PRD §3.2)."""
    defaults = {
        "full_name": "Test Resident",
        "medical_record_number": f"MRN-{_unique_suffix()}",
        "date_of_birth": "1945-01-01T00:00:00Z",
        "primary_facility_id": facility_id,
    }
    defaults.update(overrides)
    return defaults


def create_qualifying_stay_payload(**overrides) -> dict:
    """QualifyingStay: hospital_admit_at, hospital_discharge_at required.
    Defaults to a 4-midnight (qualifying) stay (PRD §3.2)."""
    defaults = {
        "hospital_admit_at": QUALIFYING_HOSPITAL_ADMIT,
        "hospital_discharge_at": QUALIFYING_HOSPITAL_DISCHARGE,
    }
    defaults.update(overrides)
    return defaults


def create_pasrr_screening_payload(**overrides) -> dict:
    """PasrrScreening: level required; has_serious_mental_illness_indicator
    optional, defaults false (PRD §3.2)."""
    defaults = {
        "level": "LEVEL_I",
        "has_serious_mental_illness_indicator": False,
    }
    defaults.update(overrides)
    return defaults


def create_admission_payload(resident_id, facility_id, pasrr_screening_id, **overrides) -> dict:
    """Admission: resident_id, facility_id, pasrr_screening_id, payer_source,
    admit_at required; qualifying_stay_id optional (PRD §3.3)."""
    defaults = {
        "resident_id": resident_id,
        "facility_id": facility_id,
        "pasrr_screening_id": pasrr_screening_id,
        "payer_source": "PRIVATE",
        "admit_at": STANDARD_ADMIT_AT,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    """MdsAssessment: assessment_type, assessment_reference_date, pt_function_score,
    slp_components_count, nta_comorbidity_points required (PRD §3.4)."""
    defaults = {
        "assessment_type": "ADMISSION_5DAY",
        "assessment_reference_date": "2026-02-05T00:00:00Z",
        "pt_function_score": 7,
        "slp_components_count": 1,
        "nta_comorbidity_points": 10,
    }
    defaults.update(overrides)
    return defaults


def create_therapy_log_payload(**overrides) -> dict:
    """TherapyLog: discipline, mode, minutes, session_date required (PRD §3.5)."""
    defaults = {
        "discipline": "PT",
        "mode": "INDIVIDUAL",
        "minutes": 60,
        "session_date": "2026-02-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_care_plan_payload(**overrides) -> dict:
    """CarePlan: review_interval_days optional, defaults 90 (PRD §3.7)."""
    defaults = {
        "review_interval_days": 90,
    }
    defaults.update(overrides)
    return defaults


def create_goal_payload(**overrides) -> dict:
    """CarePlanGoal: description, target_date required (PRD §3.7)."""
    defaults = {
        "description": "Restore mobility",
        "target_date": "2026-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bed_hold_payload(**overrides) -> dict:
    """BedHold: leave_reason, leave_start_at, expected_return_at required (PRD §3.6)."""
    defaults = {
        "leave_reason": "HOSPITAL",
        "leave_start_at": "2026-02-05T00:00:00Z",
        "expected_return_at": "2026-02-06T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(driving_assessment_id, **overrides) -> dict:
    """Claim: driving_assessment_id, period_start_at, period_end_at required (PRD §3.9)."""
    defaults = {
        "driving_assessment_id": driving_assessment_id,
        "period_start_at": "2026-02-01T00:00:00Z",
        "period_end_at": "2026-02-06T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_quality_measure_payload(**overrides) -> dict:
    """QualityMeasure: measure_code, numerator, denominator, reporting_period required (PRD §3.1)."""
    defaults = {
        "measure_code": "FALLS_WITH_INJURY",
        "numerator": 1,
        "denominator": 200,
        "reporting_period": "2026Q1",
    }
    defaults.update(overrides)
    return defaults
