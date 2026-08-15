"""Payload factories — one per creatable resource, input fields only (PRD 3.x, 4)."""
from typing import Any, Dict, Optional

from .constants import COLLEGE_TERM_DEFAULTS, HS_TERM_DEFAULTS, STANDARD_FUNDING_DEFAULTS


def create_high_school_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"name": "Northview HS", "district_code": "NV-01"}
    defaults.update(overrides)
    return defaults


def create_term_payload(institution_type: str, high_school_id: Optional[str] = None, **overrides) -> Dict[str, Any]:
    base = dict(COLLEGE_TERM_DEFAULTS) if institution_type == "COLLEGE" else dict(HS_TERM_DEFAULTS)
    base["institution_type"] = institution_type
    if high_school_id is not None:
        base["high_school_id"] = high_school_id
    base.update(overrides)
    return base


def create_student_payload(high_school_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "full_name": "Jamie Diaz",
        "high_school_id": high_school_id,
        "grade_level": 12,
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "course_code": "HIST210",
        "title": "US History",
        "college_credit_hours": 3,
        "hs_credit_units": 1.0,
        "placement_exam_code": "NONE",
        "min_placement_score": 0,
    }
    defaults.update(overrides)
    return defaults


def create_prerequisite_payload(course_id: str, requires_course_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "course_id": course_id,
        "requires_course_id": requires_course_id,
        "min_grade": "C",
    }
    defaults.update(overrides)
    return defaults


def create_placement_record_payload(student_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "student_id": student_id,
        "exam_code": "MATH",
        "score": 85,
        "taken_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(high_school_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "full_name": "Pat Quinn",
        "high_school_id": high_school_id,
    }
    defaults.update(overrides)
    return defaults


def create_credential_application_payload(
    instructor_id: str, course_id: str, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "instructor_id": instructor_id,
        "course_id": course_id,
        "qualification_summary": "MS Mathematics",
    }
    defaults.update(overrides)
    return defaults


def create_offering_payload(
    course_id: str,
    college_term_id: str,
    hs_term_id: str,
    high_school_id: str,
    instructor_id: str,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "course_id": course_id,
        "college_term_id": college_term_id,
        "hs_term_id": hs_term_id,
        "high_school_id": high_school_id,
        "instructor_id": instructor_id,
        "capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id: str, offering_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"student_id": student_id, "offering_id": offering_id}
    defaults.update(overrides)
    return defaults


def create_funding_agreement_payload(
    high_school_id: str, college_term_id: str, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "high_school_id": high_school_id,
        "college_term_id": college_term_id,
    }
    defaults.update(STANDARD_FUNDING_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_payment_payload(payer: str, amount_cents: int, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"payer": payer, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_articulation_agreement_payload(
    course_id: str, target_institution: str, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "course_id": course_id,
        "target_institution": target_institution,
        "transfer_credit_hours": 2.5,
        "min_grade_for_transfer": "C",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
