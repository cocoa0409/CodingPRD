"""Payload builders and the small amount of date arithmetic tests need.

Each builder returns a plain dict carrying the PRD-declared fields with valid
defaults, and accepts keyword overrides so a test can perturb exactly one field.
Passing ``None`` for an optional field removes it from the payload, which is how
a test exercises a declared default.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import CLOCK_START_UTC

_SENTINEL = object()


# ---------------------------------------------------------------------------
# Timestamp arithmetic
# ---------------------------------------------------------------------------


def parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, accepting both `Z` and `+00:00`."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_utc_z(moment: datetime) -> str:
    """Render an instant as `YYYY-MM-DDTHH:MM:SSZ`."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_days(value: str, days: int) -> str:
    return to_utc_z(parse_utc(value) + timedelta(days=days))


def minus_days(value: str, days: int) -> str:
    return to_utc_z(parse_utc(value) - timedelta(days=days))


def plus_minutes(value: str, minutes: int) -> str:
    return to_utc_z(parse_utc(value) + timedelta(minutes=minutes))


def days_between(earlier: str, later: str) -> int:
    return (parse_utc(later) - parse_utc(earlier)).days


def same_instant(left: Optional[str], right: Optional[str]) -> bool:
    """Compare two timestamps by instant, ignoring fractional-second rendering."""
    if left is None or right is None:
        return left is right
    return parse_utc(left) == parse_utc(right)


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the removal sentinel ``None``."""
    return {key: value for key, value in payload.items() if value is not None}


def _apply(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def clock_payload(current_utc: str = CLOCK_START_UTC) -> dict:
    return {"current_utc": current_utc}


# ---------------------------------------------------------------------------
# State policies
# ---------------------------------------------------------------------------


def state_policy_payload(state_code: str = "CT", **overrides) -> dict:
    """A `STATE_ENHANCED_ALL` no-cost-sharing policy, the workhorse of the suite."""
    base = {
        "state_code": state_code,
        "density_notice_rule": "STATE_ENHANCED_ALL",
        "lay_summary_max_reading_grade": 10,
        "lay_summary_deadline_days": 21,
        "supplemental_coverage_mandate": "COVERAGE_NO_COST_SHARING",
        "required_notice_codes": ["CT-DENS-1", "CT-SUPP-2"],
        "supplemental_cost_share_waiver_threshold_cents": 5000,
        "followup_grace_days": 60,
        "report_turnaround_days": 30,
        "urgent_report_turnaround_days": 7,
        "ce_grace_days": 90,
    }
    return _apply(base, overrides)


def ct_policy_payload(**overrides) -> dict:
    return state_policy_payload("CT", **overrides)


def ma_policy_payload(**overrides) -> dict:
    """A `STATE_DENSE_ONLY` cost-sharing policy with a grade-6 ceiling."""
    base = {
        "state_code": "MA",
        "density_notice_rule": "STATE_DENSE_ONLY",
        "lay_summary_max_reading_grade": 6,
        "lay_summary_deadline_days": 14,
        "supplemental_coverage_mandate": "COVERAGE_WITH_COST_SHARING",
        "required_notice_codes": ["MA-DENSE-NOTICE"],
        "supplemental_cost_share_waiver_threshold_cents": 5000,
        "followup_grace_days": 60,
        "report_turnaround_days": 30,
        "urgent_report_turnaround_days": 7,
        "ce_grace_days": 90,
    }
    return _apply(base, overrides)


def ri_policy_payload(**overrides) -> dict:
    """The MA policy with a de-minimis waiver high enough to absorb the share."""
    base = ma_policy_payload(
        state_code="RI",
        required_notice_codes=["RI-DENSE-NOTICE"],
        supplemental_cost_share_waiver_threshold_cents=15000,
    )
    return _apply(base, overrides)


def nv_policy_payload(**overrides) -> dict:
    """A federal-floor policy with no supplemental mandate at all."""
    base = {
        "state_code": "NV",
        "density_notice_rule": "FEDERAL_ONLY",
        "lay_summary_max_reading_grade": 8,
        "lay_summary_deadline_days": 30,
        "supplemental_coverage_mandate": "NONE",
        "followup_grace_days": 60,
        "report_turnaround_days": 30,
        "urgent_report_turnaround_days": 7,
        "ce_grace_days": 90,
    }
    return _apply(base, overrides)


def minimal_state_policy_payload(state_code: str = "OR", **overrides) -> dict:
    """Only the required fields, so every optional default is observable."""
    base = {
        "state_code": state_code,
        "density_notice_rule": "FEDERAL_ONLY",
        "lay_summary_max_reading_grade": 8,
        "lay_summary_deadline_days": 30,
        "supplemental_coverage_mandate": "NONE",
    }
    return _apply(base, overrides)


# ---------------------------------------------------------------------------
# Facilities and units
# ---------------------------------------------------------------------------


def facility_payload(state_policy_id: str, **overrides) -> dict:
    base = {
        "name": "Harbor Breast Center",
        "state_policy_id": state_policy_id,
        "accreditation_body": "ACR",
        "supplemental_concurrent_capacity": 2,
    }
    return _apply(base, overrides)


def funding_deposit_payload(amount_cents: int = 1000000, **overrides) -> dict:
    base = {"amount_cents": amount_cents, "memo": "Accreditation application fees"}
    return _apply(base, overrides)


def unit_payload(**overrides) -> dict:
    base = {
        "manufacturer": "Hologic",
        "model_serial": "SEL-9001",
        "modality": "DBT_3D",
        "accreditation_expires_on": "2027-06-30T00:00:00Z",
    }
    return _apply(base, overrides)


# ---------------------------------------------------------------------------
# Personnel and credits
# ---------------------------------------------------------------------------


def personnel_payload(role_type: str = "TECHNOLOGIST", **overrides) -> dict:
    base = {
        "full_name": "Tomas Tech",
        "role_type": role_type,
        "initial_qualification_on": "2024-02-01T00:00:00Z",
        "initial_training_hours": 45,
        "initial_read_volume": 30,
        "modality_certifications": ["DM_2D", "DBT_3D"],
    }
    return _apply(base, overrides)


def qualified_physician_payload(**overrides) -> dict:
    """60 hours and 240 volume are the physician thresholds; these clear both."""
    base = personnel_payload(
        role_type="INTERPRETING_PHYSICIAN",
        full_name="Rosa Radiologist",
        initial_qualification_on="2024-03-01T00:00:00Z",
        initial_training_hours=65,
        initial_read_volume=260,
    )
    return _apply(base, overrides)


def qualified_technologist_payload(**overrides) -> dict:
    """40 hours and 25 volume are the technologist thresholds; these clear both."""
    base = personnel_payload(
        role_type="TECHNOLOGIST",
        full_name="Tomas Tech",
        initial_qualification_on="2024-02-01T00:00:00Z",
        initial_training_hours=45,
        initial_read_volume=30,
    )
    return _apply(base, overrides)


def qualified_physicist_payload(**overrides) -> dict:
    """20 hours and 1 volume are the physicist thresholds; these clear both."""
    base = personnel_payload(
        role_type="MEDICAL_PHYSICIST",
        full_name="Pia Physicist",
        initial_qualification_on="2024-01-15T00:00:00Z",
        initial_training_hours=25,
        initial_read_volume=3,
    )
    return _apply(base, overrides)


def ce_credit_payload(ce_hours: float = 8.0, awarded_on: str = "2026-06-01T00:00:00Z", **overrides) -> dict:
    base = {
        "credit_type": "CATEGORY_1_CE",
        "awarded_on": awarded_on,
        "ce_hours": ce_hours,
        "source_note": "Annual MQSA update course",
    }
    return _apply(base, overrides)


def volume_credit_payload(exam_count: int = 200, awarded_on: str = "2026-06-01T00:00:00Z", **overrides) -> dict:
    base = {
        "credit_type": "READ_VOLUME",
        "awarded_on": awarded_on,
        "exam_count": exam_count,
        "source_note": "Quarterly volume attestation",
    }
    return _apply(base, overrides)


def qualification_review_payload(**overrides) -> dict:
    base = {"review_note": "Scheduled review"}
    return _apply(base, overrides)


# ---------------------------------------------------------------------------
# Physicist surveys and equipment failures
# ---------------------------------------------------------------------------


def survey_payload(**overrides) -> dict:
    base = {
        "survey_type": "ANNUAL",
        "effective_start": "2026-07-01T00:00:00Z",
        "effective_end": "2027-07-01T00:00:00Z",
    }
    return _apply(base, overrides)


def passing_survey_decision_payload(**overrides) -> dict:
    """Phantom score at or above 6.0, dose at or below 3.00, no deficiency codes."""
    base = {
        "phantom_score": 7.0,
        "mean_glandular_dose_mgy": 2.00,
        "critical_deficiency_codes": [],
        "outcome_note": "Within tolerance",
    }
    return _apply(base, overrides)


def failing_survey_decision_payload(**overrides) -> dict:
    """A phantom score below 6.0 together with a recorded critical deficiency."""
    base = {
        "phantom_score": 5.0,
        "mean_glandular_dose_mgy": 4.00,
        "critical_deficiency_codes": ["PHANTOM_LOW"],
        "outcome_note": "Phantom score below tolerance",
    }
    return _apply(base, overrides)


def equipment_failure_payload(**overrides) -> dict:
    base = {
        "failure_code": "DETECTOR",
        "severity": "MAJOR",
        "detected_at": "2026-08-01T00:00:00Z",
    }
    return _apply(base, overrides)


def restore_payload(**overrides) -> dict:
    base = {"repair_note": "Detector module replaced and verified"}
    return _apply(base, overrides)


# ---------------------------------------------------------------------------
# Clinical image reviews
# ---------------------------------------------------------------------------


def packet_payload(exam_ids: List[str], expected_unit_version: int, **overrides) -> dict:
    base = {
        "exam_ids": list(exam_ids),
        "expected_unit_version": expected_unit_version,
        "reviewer_note": "Annual clinical image packet",
    }
    return _apply(base, overrides)


def review_decision_payload(decision: str = "PASS", **overrides) -> dict:
    base = {"decision": decision, "reviewer_note": "Accreditation body decision"}
    if decision == "REVISION_REQUIRED":
        base["deficiency_categories"] = ["POSITIONING"]
    return _apply(base, overrides)


def withdraw_payload(**overrides) -> dict:
    base = {"withdrawal_reason": "Packet assembled from the wrong study set"}
    return _apply(base, overrides)


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------


def inspection_payload(level: str = "NONE", **overrides) -> dict:
    base = {
        "inspection_date": "2026-07-28T00:00:00Z",
        "inspector_findings_level": level,
        "finding_codes": [],
    }
    return _apply(base, overrides)


def close_inspection_payload(**overrides) -> dict:
    base = {"closure_note": "Corrective action accepted"}
    return _apply(base, overrides)


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------


def exam_payload(unit_id: str, technologist_id: str, **overrides) -> dict:
    base = {
        "unit_id": unit_id,
        "technologist_id": technologist_id,
        "patient_ref": "PT-1001",
        "patient_state_code": "CT",
        "exam_type": "SCREENING",
        "performed_at": "2026-07-20T00:00:00Z",
        "original_image_count": 4,
    }
    return _apply(base, overrides)


def interpret_payload(birads_assessment: int = 1, density_category: Optional[str] = "B", **overrides) -> dict:
    base = {"birads_assessment": birads_assessment}
    if density_category is not None:
        base["density_category"] = density_category
    return _apply(base, overrides)


def amend_payload(**overrides) -> dict:
    base = {"amendment_reason": "Second read on comparison films"}
    return _apply(base, overrides)


def outcome_payload(biopsy_performed: bool = True, pathology_result: str = "BENIGN", **overrides) -> dict:
    base = {"biopsy_performed": biopsy_performed, "pathology_result": pathology_result}
    return _apply(base, overrides)


def repeat_record_payload(reason_code: str = "POSITIONING", repeat_image_count: int = 2, **overrides) -> dict:
    base = {"reason_code": reason_code, "repeat_image_count": repeat_image_count}
    return _apply(base, overrides)


def retract_payload(**overrides) -> dict:
    base = {"retraction_reason": "Logged against the wrong patient"}
    return _apply(base, overrides)


# ---------------------------------------------------------------------------
# Notification letters
# ---------------------------------------------------------------------------


def letter_payload(expected_exam_version: int, **overrides) -> dict:
    base = {"expected_exam_version": expected_exam_version}
    return _apply(base, overrides)


def undeliverable_payload(**overrides) -> dict:
    base = {"undeliverable_reason": "Returned by the postal service"}
    return _apply(base, overrides)


# ---------------------------------------------------------------------------
# Supplemental orders
# ---------------------------------------------------------------------------


def supplemental_order_payload(modality: str = "ULTRASOUND", **overrides) -> dict:
    base = {"modality": modality, "recommendation_note": "Dense tissue"}
    return _apply(base, overrides)


def schedule_payload(appointment_start: str = "2026-08-01T09:00:00Z", **overrides) -> dict:
    base = {"appointment_start": appointment_start}
    return _apply(base, overrides)


def complete_order_payload(**overrides) -> dict:
    base = {"completion_note": "Study performed"}
    return _apply(base, overrides)


# ---------------------------------------------------------------------------
# Audit cycles
# ---------------------------------------------------------------------------


def audit_cycle_payload(
    period_start: str = "2026-01-01T00:00:00Z",
    period_end: str = "2026-07-01T00:00:00Z",
    **overrides,
) -> dict:
    base = {"period_start": period_start, "period_end": period_end}
    return _apply(base, overrides)


def close_cycle_payload(variant: str = "PPV1_SCREENING", **overrides) -> dict:
    base = {"variant": variant}
    return _apply(base, overrides)
