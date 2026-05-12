"""Payload factories — one factory per input-bearing endpoint.

Each factory emits ONLY the fields PRD §3 declares as input (source: input)
for the relevant endpoint. Tests override via kwargs.

Field names mirror PRD prose exactly — no abbreviation, no guessing.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_GPA_X100,
    DEFAULT_GRADE,
    DEFAULT_MAJOR,
    DEFAULT_OUTLIER_Z_THRESHOLD_X100,
    DEFAULT_REVIEWER_DEPT,
    DEFAULT_STUDENT_DEPT,
)


def unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def unique_code(prefix: str = "SCH") -> str:
    """Unique scholarship code, between 3 and 32 chars (PRD §3.1)."""
    return f"{prefix}-{unique_suffix()}"


# ---------------------------------------------------------------------------
# Scholarship (PRD §3.1)
# ---------------------------------------------------------------------------
def create_scholarship_payload(
    *,
    code: Optional[str] = None,
    name: Optional[str] = None,
    category: str = "MERIT",
    per_award_amount_cents: int = 1_000_000,
    total_quota: int = 1,
    gpa_threshold_x100: int = 300,
    eligible_majors: Optional[List[str]] = None,
    eligible_grades: Optional[List[int]] = None,
    family_income_ceiling_cents: Optional[int] = None,
    required_materials: Optional[List[str]] = None,
    application_window_start: str = "2026-06-01T00:00:00Z",
    application_window_end: str = "2026-06-30T00:00:00Z",
    announcement_window_end: str = "2026-07-15T00:00:00Z",
    rubric_weights: Optional[Dict[str, int]] = None,
    outlier_z_threshold_x100: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'the award's identifying `code` (unique across all
    scholarships, between 3 and 32 characters inclusive), its human-readable
    `name`, and the `category` ... The award value is captured as
    `per_award_amount_cents`, an integer at least 1, and the total number
    of recipients across all departments as `total_quota`, also at least 1.'
    """
    payload: Dict[str, Any] = {
        "code": code or unique_code(),
        "name": name or f"Scholarship {unique_suffix()}",
        "category": category,
        "per_award_amount_cents": per_award_amount_cents,
        "total_quota": total_quota,
        "gpa_threshold_x100": gpa_threshold_x100,
        "eligible_majors": (
            eligible_majors if eligible_majors is not None else []
        ),
        "eligible_grades": (
            eligible_grades if eligible_grades is not None else []
        ),
        "required_materials": (
            required_materials if required_materials is not None
            else ["TRANSCRIPT"]
        ),
        "application_window_start": application_window_start,
        "application_window_end": application_window_end,
        "announcement_window_end": announcement_window_end,
        "rubric_weights": (
            rubric_weights if rubric_weights is not None else {"core": 100}
        ),
    }
    # NEED-only field. PRD §3.1: 'family_income_ceiling_cents ... must be
    # null for any non-NEED category.'
    if category == "NEED":
        payload["family_income_ceiling_cents"] = (
            family_income_ceiling_cents
            if family_income_ceiling_cents is not None
            else 10_000_000
        )
    else:
        if family_income_ceiling_cents is not None:
            payload["family_income_ceiling_cents"] = (
                family_income_ceiling_cents
            )
        else:
            payload["family_income_ceiling_cents"] = None

    if outlier_z_threshold_x100 is not None:
        payload["outlier_z_threshold_x100"] = outlier_z_threshold_x100

    payload.update(overrides)
    return payload


def patch_scholarship_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §4 PATCH /scholarships allows
    {name?, per_award_amount_cents?, rubric_weights?, required_materials?,
    outlier_z_threshold_x100?, version}.
    """
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def scholarship_state_payload(to_status: str,
                              version: Optional[int] = None,
                              **overrides: Any) -> Dict[str, Any]:
    """PRD §4: POST /scholarships/{id}/state body has {to_status, version?}."""
    payload: Dict[str, Any] = {"to_status": to_status}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# QuotaAllocation (PRD §3.1)
# ---------------------------------------------------------------------------
def create_quota_allocation_payload(
    *,
    department_code: str = DEFAULT_STUDENT_DEPT,
    grade: int = DEFAULT_GRADE,
    special_group: Optional[str] = None,
    initial_slots: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Each quota slice is a QuotaAllocation row that belongs to
    a parent scholarship and carries a department_code, a grade ..., and a
    special_group qualifier ... The initial_slots field captures the
    originally allocated count for this slice (a non-negative integer).'"""
    payload: Dict[str, Any] = {
        "department_code": department_code,
        "grade": grade,
        "initial_slots": initial_slots,
    }
    if special_group is not None:
        payload["special_group"] = special_group
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reviewer (PRD §3.5)
# ---------------------------------------------------------------------------
def create_reviewer_payload(
    *,
    full_name: Optional[str] = None,
    department_code: str = DEFAULT_REVIEWER_DEPT,
    family_relation_student_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'a new Reviewer is created with a full_name, a home
    department_code, and an optional family_relation_student_ids array.'"""
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Reviewer {unique_suffix()}",
        "department_code": department_code,
    }
    if family_relation_student_ids is not None:
        payload["family_relation_student_ids"] = (
            family_relation_student_ids
        )
    payload.update(overrides)
    return payload


def patch_reviewer_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH /reviewers/{id} body — status? family_relation_student_ids?
    version. See PRD §3.5."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Application (PRD §3.3)
# ---------------------------------------------------------------------------
def create_application_payload(
    *,
    student_department_code: str = DEFAULT_STUDENT_DEPT,
    student_advisor_id: Optional[str] = None,
    student_major: str = DEFAULT_MAJOR,
    student_grade: int = DEFAULT_GRADE,
    student_gpa_x100: int = DEFAULT_GPA_X100,
    student_family_income_cents: Optional[int] = None,
    student_special_group: Optional[str] = None,
    uploaded_materials: Optional[List[str]] = None,
    advisor_recommendation_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'the Student posts payload fields that the server stamps
    onto the new Application: student_department_code ..., student_advisor_id
    ..., student_major, student_grade, and student_gpa_x100.' For NEED:
    'student_family_income_cents must be supplied — the field is otherwise
    null.' An optional student_special_group (default NONE)."""
    payload: Dict[str, Any] = {
        "student_department_code": student_department_code,
        # PRD §3.3 lists student_advisor_id alongside required creation
        # payload fields; default to a stable opaque id so the field is
        # always present.
        "student_advisor_id": (
            student_advisor_id
            if student_advisor_id is not None
            else f"advisor-{unique_suffix()}"
        ),
        "student_major": student_major,
        "student_grade": student_grade,
        "student_gpa_x100": student_gpa_x100,
        "uploaded_materials": (
            uploaded_materials if uploaded_materials is not None
            else ["TRANSCRIPT"]
        ),
    }
    if student_family_income_cents is not None:
        payload["student_family_income_cents"] = (
            student_family_income_cents
        )
    if student_special_group is not None:
        payload["student_special_group"] = student_special_group
    if advisor_recommendation_id is not None:
        payload["advisor_recommendation_id"] = advisor_recommendation_id
    payload.update(overrides)
    return payload


def patch_application_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH /scholarships/{id}/applications/{id} — optional form-field
    edits while DRAFT (PRD §3.3 and §4)."""
    return dict(overrides)


def dept_review_payload(
    *,
    decision: str = "PASS",
    comment: str = "ok",
    is_authentic_flags: Optional[Dict[str, bool]] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'a decision of either PASS or REJECT against an
    application, plus a comment, plus an is_authentic_flags map asserting
    that each item in the application's uploaded_materials has been
    authenticated.'"""
    payload: Dict[str, Any] = {
        "decision": decision,
        "comment": comment,
    }
    if is_authentic_flags is not None:
        payload["is_authentic_flags"] = is_authentic_flags
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def correct_application_payload(
    *,
    replaced_materials: Optional[List[str]] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'a replaced_materials array, each entry of which must
    already be present in the application's current uploaded_materials.'"""
    payload: Dict[str, Any] = {
        "replaced_materials": (
            replaced_materials if replaced_materials is not None else []
        ),
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def assign_reviewers_payload(
    *,
    reviewer_ids: List[str],
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'reviewer_ids containing exactly three reviewer ids'."""
    payload: Dict[str, Any] = {"reviewer_ids": list(reviewer_ids)}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Score (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------
def submit_score_payload(
    *,
    criterion_scores: Dict[str, int],
    comment: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'criterion_scores — an object whose keys must be exactly
    the set of keys of the scholarship's rubric_weights ... and whose values
    are integers in the range 0 to 100 inclusive — and an optional comment.'
    """
    payload: Dict[str, Any] = {"criterion_scores": dict(criterion_scores)}
    if comment is not None:
        payload["comment"] = comment
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Objection (PRD §3.9)
# ---------------------------------------------------------------------------
def create_objection_payload(
    *,
    application_id: str,
    objector_student_id: str,
    reason_code: str = "MATERIAL_FALSE",
    description: str = "Issue raised",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.9: 'objection payload carries the application_id of the
    application being objected to, an objector_student_id ..., a
    reason_code of one of MATERIAL_FALSE, SCORING_ERROR, ELIGIBILITY_BREACH,
    or COI_BREACH, and a free-form description.'"""
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "objector_student_id": objector_student_id,
        "reason_code": reason_code,
        "description": description,
    }
    payload.update(overrides)
    return payload


def rule_objection_payload(
    *,
    decision: str,
    ruling_comment: str = "Ruling reasoning",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.9: 'a SchoolAdmin rules on a PENDING objection by issuing a
    decision of UPHOLD or DISMISS, together with a ruling_comment.'"""
    payload: Dict[str, Any] = {
        "decision": decision,
        "ruling_comment": ruling_comment,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DisbursementPlan (PRD §3.10)
# ---------------------------------------------------------------------------
def create_disbursement_plan_payload(
    *,
    payment_channel: str = "BANK",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.10: 'plan's payload carries the default payment_channel of
    BANK or CAMPUS_CARD.'"""
    payload: Dict[str, Any] = {"payment_channel": payment_channel}
    payload.update(overrides)
    return payload


def approve_disbursement_plan_payload(
    *,
    level: str,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.10: approval body has {level: DEPT | FINANCE, version?}."""
    payload: Dict[str, Any] = {"level": level}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock (PRD §2.10)
# ---------------------------------------------------------------------------
def clock_payload(to_iso: str) -> Dict[str, Any]:
    """PRD §2.10: 'the to field of the clock-advance endpoint.'"""
    return {"to": to_iso}


__all__ = [
    "unique_suffix",
    "unique_code",
    "create_scholarship_payload",
    "patch_scholarship_payload",
    "scholarship_state_payload",
    "create_quota_allocation_payload",
    "create_reviewer_payload",
    "patch_reviewer_payload",
    "create_application_payload",
    "patch_application_payload",
    "dept_review_payload",
    "correct_application_payload",
    "assign_reviewers_payload",
    "submit_score_payload",
    "create_objection_payload",
    "rule_objection_payload",
    "create_disbursement_plan_payload",
    "approve_disbursement_plan_payload",
    "clock_payload",
    "DEFAULT_OUTLIER_Z_THRESHOLD_X100",
]
