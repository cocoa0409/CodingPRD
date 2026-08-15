"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    DISTRICT_DIRECTOR = "District504Director"
    COORDINATOR = "Section504Coordinator"
    TEACHER = "Teacher"
    PRINCIPAL = "SchoolPrincipal"
    PARENT = "Parent"


class StaffRole(str, Enum):
    TEACHER = "TEACHER"
    COORDINATOR = "COORDINATOR"
    PRINCIPAL = "PRINCIPAL"
    DISTRICT_DIRECTOR = "DISTRICT_DIRECTOR"


class SchoolPosture(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    PROBATION = "PROBATION"
    AUDIT_HOLD = "AUDIT_HOLD"


class Student504Status(str, Enum):
    NONE = "NONE"
    REFERRED = "REFERRED"
    EVALUATING = "EVALUATING"
    PLAN_ACTIVE = "PLAN_ACTIVE"
    PLAN_SUSPENDED = "PLAN_SUSPENDED"
    EXITED_TO_IEP = "EXITED_TO_IEP"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    TERMINATED = "TERMINATED"


class IepStatus(str, Enum):
    NONE = "NONE"
    IEP_ACTIVE = "IEP_ACTIVE"
    IEP_EXITED = "IEP_EXITED"


class TrainingStatus(str, Enum):
    UNTRAINED = "UNTRAINED"
    TRAINED_CURRENT = "TRAINED_CURRENT"
    TRAINED_EXPIRED = "TRAINED_EXPIRED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    EVALUATION_INITIATED = "EVALUATION_INITIATED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class EvaluationStatus(str, Enum):
    INITIATED = "INITIATED"
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_RECEIVED = "CONSENT_RECEIVED"
    EVALUATION_IN_PROGRESS = "EVALUATION_IN_PROGRESS"
    DETERMINATION_MADE = "DETERMINATION_MADE"
    CANCELLED = "CANCELLED"


class DeterminationOutcome(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PARENT_CONSENT = "PENDING_PARENT_CONSENT"
    PENDING_TEACHER_ACK = "PENDING_TEACHER_ACK"
    ACTIVE = "ACTIVE"
    UNDER_ANNUAL_REVIEW = "UNDER_ANNUAL_REVIEW"
    SUSPENDED = "SUSPENDED"
    EXITED_TO_IEP = "EXITED_TO_IEP"
    TERMINATED = "TERMINATED"


class AccommodationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISCONTINUED = "DISCONTINUED"


class AccommodationType(str, Enum):
    EXTENDED_TIME = "EXTENDED_TIME"
    PREFERENTIAL_SEATING = "PREFERENTIAL_SEATING"
    REDUCED_WORKLOAD = "REDUCED_WORKLOAD"
    BREAKS_AS_NEEDED = "BREAKS_AS_NEEDED"
    ASSISTIVE_TECH = "ASSISTIVE_TECH"
    MODIFIED_GRADING = "MODIFIED_GRADING"
    OTHER = "OTHER"


class AckStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DECLINED = "DECLINED"


class ReviewType(str, Enum):
    ANNUAL = "ANNUAL"
    RE_EVALUATION = "RE_EVALUATION"
    PARENT_REQUESTED = "PARENT_REQUESTED"
    DISTRICT_AUDIT = "DISTRICT_AUDIT"


class ReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class ReviewOutcome(str, Enum):
    CONTINUE_PLAN = "CONTINUE_PLAN"
    MODIFY_PLAN = "MODIFY_PLAN"
    EXIT_TO_IEP = "EXIT_TO_IEP"
    TERMINATE_504 = "TERMINATE_504"


class TestingRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDING_DISTRICT_REVIEW = "PENDING_DISTRICT_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    FLAGGED_FOR_STATE_AUDIT = "FLAGGED_FOR_STATE_AUDIT"


class ConsentScope(str, Enum):
    INITIAL_PLAN = "INITIAL_PLAN"
    PLAN_AMENDMENT = "PLAN_AMENDMENT"
    RE_EVALUATION = "RE_EVALUATION"
    EXIT_TO_IEP = "EXIT_TO_IEP"
    TESTING_ACCOMMODATION = "TESTING_ACCOMMODATION"


class ConsentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class GrievanceStatus(str, Enum):
    FILED = "FILED"
    INFORMAL_RESOLUTION = "INFORMAL_RESOLUTION"
    FORMAL_INVESTIGATION = "FORMAL_INVESTIGATION"
    RESOLVED = "RESOLVED"
    ESCALATED_TO_OCR = "ESCALATED_TO_OCR"
    CLOSED = "CLOSED"


class GrievanceCategory(str, Enum):
    DISCRIMINATION = "DISCRIMINATION"
    NON_IMPLEMENTATION = "NON_IMPLEMENTATION"
    PROCEDURAL_VIOLATION = "PROCEDURAL_VIOLATION"
    RETALIATION = "RETALIATION"
    OTHER = "OTHER"


class DisabilityCategory(str, Enum):
    PHYSICAL = "PHYSICAL"
    MENTAL = "MENTAL"
    LEARNING = "LEARNING"
    CHRONIC_HEALTH = "CHRONIC_HEALTH"
    OTHER = "OTHER"


class TrainingTopic(str, Enum):
    SECTION_504_BASICS = "SECTION_504_BASICS"
    ACCOMMODATION_DELIVERY = "ACCOMMODATION_DELIVERY"
    GRIEVANCE_PROCEDURES = "GRIEVANCE_PROCEDURES"
    TESTING_ACCOMMODATIONS = "TESTING_ACCOMMODATIONS"
    TRANSITION_PROCEDURES = "TRANSITION_PROCEDURES"


class AuditEventType(str, Enum):
    REFERRAL_SUBMITTED = "REFERRAL_SUBMITTED"
    REFERRAL_REVIEWED = "REFERRAL_REVIEWED"
    EVALUATION_INITIATED = "EVALUATION_INITIATED"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    CONSENT_DENIED = "CONSENT_DENIED"
    DETERMINATION_MADE = "DETERMINATION_MADE"
    PLAN_ACTIVATED = "PLAN_ACTIVATED"
    PLAN_SUSPENDED = "PLAN_SUSPENDED"
    PLAN_TERMINATED = "PLAN_TERMINATED"
    REVIEW_COMPLETED_LATE = "REVIEW_COMPLETED_LATE"
    REVIEW_OVERDUE = "REVIEW_OVERDUE"
    TEST_ACCOMM_DENIED = "TEST_ACCOMM_DENIED"
    GRIEVANCE_FILED = "GRIEVANCE_FILED"
    GRIEVANCE_ESCALATED = "GRIEVANCE_ESCALATED"
    TRAINING_LAPSED = "TRAINING_LAPSED"
    POSTURE_CHANGED = "POSTURE_CHANGED"
    OCC_CONFLICT = "OCC_CONFLICT"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# ComplianceAuditEvent is the append-only exception: only id + created_at.


class School(TypedDict, total=False):
    id: str
    school_name: str
    district_code: str
    school_posture: str
    current_academic_year: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    school_id: str
    student_external_ref: str
    full_name: str
    date_of_birth: str
    grade_level: int
    section_504_status: str
    iep_status: str
    has_active_504_plan: bool
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    school_id: str
    staff_external_ref: str
    full_name: str
    staff_role: str
    is_active: bool
    current_training_status: str
    created_at: str
    updated_at: str
    version: int


class Section504Referral(TypedDict, total=False):
    id: str
    student_id: str
    submitted_by_staff_id: str
    referral_reason: str
    suspected_disability_category: str
    referral_status: str
    submitted_at: str
    review_deadline: str
    created_at: str
    updated_at: str
    version: int


class EligibilityEvaluation(TypedDict, total=False):
    id: str
    student_id: str
    referral_id: str
    supersedes_evaluation_id: Optional[str]
    evaluation_status: str
    parent_consent_obtained_at: Optional[str]
    evaluation_started_at: Optional[str]
    determination_deadline: Optional[str]
    determination_outcome: Optional[str]
    disability_impairment_found: bool
    major_life_activity_affected: bool
    determined_by_staff_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Section504Plan(TypedDict, total=False):
    id: str
    student_id: str
    evaluation_id: str
    plan_status: str
    drafted_by_staff_id: str
    plan_effective_date: Optional[str]
    next_annual_review_due: Optional[str]
    next_re_evaluation_due: Optional[str]
    implementation_compliance_pct: float
    all_teachers_acknowledged: bool
    created_at: str
    updated_at: str
    version: int


class Accommodation(TypedDict, total=False):
    id: str
    plan_id: str
    accommodation_type: str
    description: str
    accommodation_status: str
    applies_to_testing: bool
    created_at: str
    updated_at: str
    version: int


class TeacherAcknowledgment(TypedDict, total=False):
    id: str
    plan_id: str
    staff_id: str
    ack_status: str
    ack_requested_at: str
    ack_responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImplementationLog(TypedDict, total=False):
    id: str
    plan_id: str
    accommodation_id: str
    logged_by_staff_id: str
    log_date: str
    was_implemented_as_planned: bool
    deviation_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewEvent(TypedDict, total=False):
    id: str
    plan_id: str
    review_type: str
    review_status: str
    scheduled_for: str
    completed_at: Optional[str]
    outcome: Optional[str]
    was_late: bool
    created_at: str
    updated_at: str
    version: int


class TestingAccommodationRequest(TypedDict, total=False):
    id: str
    plan_id: str
    accommodation_id: str
    test_name: str
    test_date: str
    request_status: str
    submitted_at: str
    reviewed_by_staff_id: Optional[str]
    review_deadline: str
    created_at: str
    updated_at: str
    version: int


class ParentConsentRecord(TypedDict, total=False):
    id: str
    student_id: str
    evaluation_id: Optional[str]
    plan_id: Optional[str]
    consent_scope: str
    consent_status: str
    requested_at: str
    responded_at: Optional[str]
    responded_by_parent_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Grievance(TypedDict, total=False):
    id: str
    student_id: str
    plan_id: Optional[str]
    filed_by_parent_ref: str
    grievance_category: str
    description: str
    grievance_status: str
    filed_at: str
    resolution_deadline: Optional[str]
    resolved_by_staff_id: Optional[str]
    intake_staff_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffTrainingRecord(TypedDict, total=False):
    id: str
    staff_id: str
    training_topic: str
    trained_at: str
    expires_at: str
    training_status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceAuditEvent(TypedDict, total=False):
    # Append-only ledger entry (PRD §2.4): carries ONLY id + created_at from the
    # common set — no updated_at, no version.
    id: str
    created_at: str
    school_id: str
    event_type: str
    entity_ref: str
    actor_staff_id: Optional[str]
    event_payload: dict
