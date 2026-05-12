"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Status enums enumerate the strings the
server accepts and emits per PRD §3.

PRD §2.4 split:
- Versioned entities (id + created_at + updated_at + version):
  Scholarship, QuotaAllocation, Reviewer, Application, Objection,
  DisbursementPlan.
- Append-only entities (id + created_at ONLY, no updated_at / no version):
  ReviewerAssignment, Score, DisbursementRecord, AuditEvent,
  ExternalSyncEvent.
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SCHOOL_ADMIN = "SchoolAdmin"
    DEPT_OFFICER = "DeptOfficer"
    FINANCE_OFFICER = "FinanceOfficer"
    STUDENT = "Student"
    REVIEWER = "Reviewer"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.1–§3.11)
# ---------------------------------------------------------------------------
class ScholarshipStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    REVIEWING = "REVIEWING"
    ANNOUNCED = "ANNOUNCED"
    FINALIZED = "FINALIZED"
    DISBURSED = "DISBURSED"


class ScholarshipCategory(str, Enum):
    MERIT = "MERIT"
    NEED = "NEED"
    RESEARCH = "RESEARCH"
    SPECIAL_GROUP = "SPECIAL_GROUP"


class MaterialCode(str, Enum):
    TRANSCRIPT = "TRANSCRIPT"
    AWARD_CERT = "AWARD_CERT"
    POVERTY_PROOF = "POVERTY_PROOF"
    ADVISOR_REC = "ADVISOR_REC"


class SpecialGroup(str, Enum):
    NONE = "NONE"
    GENDER_FEMALE = "GENDER_FEMALE"
    GENDER_MALE = "GENDER_MALE"
    ETHNIC_MINORITY = "ETHNIC_MINORITY"
    DISABILITY = "DISABILITY"


class ReviewerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DEPT_PRELIM_PASSED = "DEPT_PRELIM_PASSED"
    DEPT_PRELIM_REJECTED = "DEPT_PRELIM_REJECTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVIEW_COMPLETE = "REVIEW_COMPLETE"
    AWARDED = "AWARDED"
    NOT_AWARDED = "NOT_AWARDED"
    WITHDRAWN = "WITHDRAWN"
    DISBURSED = "DISBURSED"
    REVOKED = "REVOKED"


class RevocationReason(str, Enum):
    OBJECTION_UPHELD = "OBJECTION_UPHELD"
    AUDIT_FAILURE = "AUDIT_FAILURE"


class ObjectionStatus(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class ObjectionReasonCode(str, Enum):
    MATERIAL_FALSE = "MATERIAL_FALSE"
    SCORING_ERROR = "SCORING_ERROR"
    ELIGIBILITY_BREACH = "ELIGIBILITY_BREACH"
    COI_BREACH = "COI_BREACH"


class DisbursementPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    DEPT_APPROVED = "DEPT_APPROVED"
    FINANCE_APPROVED = "FINANCE_APPROVED"
    EXECUTED = "EXECUTED"
    ARCHIVED = "ARCHIVED"


class PaymentChannel(str, Enum):
    BANK = "BANK"
    CAMPUS_CARD = "CAMPUS_CARD"


class AuditEventType(str, Enum):
    APPLICATION_SUBMITTED = "APPLICATION_SUBMITTED"
    APPLICATION_WITHDRAWN = "APPLICATION_WITHDRAWN"
    DEPT_REVIEW = "DEPT_REVIEW"
    SCORE_SUBMITTED = "SCORE_SUBMITTED"
    AGGREGATION_DONE = "AGGREGATION_DONE"
    FINALIZED = "FINALIZED"
    OBJECTION_RULED = "OBJECTION_RULED"
    DISBURSEMENT_APPROVED = "DISBURSEMENT_APPROVED"
    DISBURSEMENT_EXECUTED = "DISBURSEMENT_EXECUTED"
    EXT_SYNC_EMITTED = "EXT_SYNC_EMITTED"


class ExternalSyncKind(str, Enum):
    ACADEMIC_AFFAIRS_FINALIZED = "ACADEMIC_AFFAIRS_FINALIZED"
    FINANCE_DISBURSED = "FINANCE_DISBURSED"
    IM_NOTIFY_AWARD = "IM_NOTIFY_AWARD"
    IM_NOTIFY_REJECT = "IM_NOTIFY_REJECT"
    IM_NOTIFY_OBJECTION_RULING = "IM_NOTIFY_OBJECTION_RULING"


# ---------------------------------------------------------------------------
# Versioned entities — common fields: id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class Scholarship(TypedDict, total=False):
    id: str
    code: str
    name: str
    category: str
    per_award_amount_cents: int
    total_quota: int
    gpa_threshold_x100: int
    eligible_majors: List[str]
    eligible_grades: List[int]
    family_income_ceiling_cents: Optional[int]
    required_materials: List[str]
    application_window_start: str
    application_window_end: str
    announcement_window_end: str
    status: str
    rubric_weights: dict
    outlier_z_threshold_x100: int
    created_at: str
    updated_at: str
    version: int


class QuotaAllocation(TypedDict, total=False):
    id: str
    scholarship_id: str
    department_code: str
    grade: int
    special_group: str
    initial_slots: int
    current_slots: int
    filled_slots: int
    reallocated_from_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict, total=False):
    id: str
    full_name: str
    department_code: str
    family_relation_student_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    scholarship_id: str
    student_id: str
    student_department_code: str
    student_advisor_id: Optional[str]
    student_major: str
    student_grade: int
    student_gpa_x100: int
    student_family_income_cents: Optional[int]
    student_special_group: str
    uploaded_materials: List[str]
    advisor_recommendation_id: Optional[str]
    status: str
    dept_review_comment: Optional[str]
    aggregated_score_x100: Optional[int]
    final_rank: Optional[int]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Objection(TypedDict, total=False):
    id: str
    application_id: str
    objector_student_id: str
    reason_code: str
    description: str
    status: str
    ruling_comment: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisbursementPlan(TypedDict, total=False):
    id: str
    scholarship_id: str
    payment_channel: str
    status: str
    total_gross_cents: int
    total_tax_cents: int
    total_net_cents: int
    dept_approver_id: Optional[str]
    finance_approver_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at ONLY (PRD §2.4)
# ---------------------------------------------------------------------------
class ReviewerAssignment(TypedDict, total=False):
    id: str
    application_id: str
    reviewer_id: str
    assigned_at: str
    created_at: str


class Score(TypedDict, total=False):
    id: str
    application_id: str
    reviewer_id: str
    criterion_scores: dict
    raw_total_x100: int
    is_outlier: bool
    comment: Optional[str]
    created_at: str


class DisbursementRecord(TypedDict, total=False):
    id: str
    plan_id: str
    application_id: str
    student_id: str
    gross_cents: int
    tax_withheld_cents: int
    net_cents: int
    payment_channel: str
    executed_at: str
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    event_type: str
    actor_role: str
    actor_id: str
    target_entity: str
    target_id: str
    payload: dict
    created_at: str


class ExternalSyncEvent(TypedDict, total=False):
    id: str
    kind: str
    application_id: Optional[str]
    scholarship_id: str
    payload: dict
    created_at: str


__all__ = [
    "UserRole",
    "ScholarshipStatus",
    "ScholarshipCategory",
    "MaterialCode",
    "SpecialGroup",
    "ReviewerStatus",
    "ApplicationStatus",
    "RevocationReason",
    "ObjectionStatus",
    "ObjectionReasonCode",
    "DisbursementPlanStatus",
    "PaymentChannel",
    "AuditEventType",
    "ExternalSyncKind",
    "Scholarship",
    "QuotaAllocation",
    "Reviewer",
    "Application",
    "Objection",
    "DisbursementPlan",
    "ReviewerAssignment",
    "Score",
    "DisbursementRecord",
    "AuditEvent",
    "ExternalSyncEvent",
]
