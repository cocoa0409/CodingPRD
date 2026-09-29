"""Domain types for the Work-Based Learning API: status enums, role enum, entity TypedDicts.

Field names mirror the PRD exactly. Entities that carry the common system fields
expose ``id``, ``created_at``, ``updated_at`` and ``version``; ``LearningObjective``
is the single exception described by the PRD and carries only ``id`` and ``created_at``.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    WBL_COORDINATOR = "WblCoordinator"
    SAFETY_REVIEWER = "SafetyReviewer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    EMPLOYER_SUPERVISOR = "EmployerSupervisor"
    STUDENT = "Student"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class IndustrySector(str, Enum):
    MANUFACTURING = "MANUFACTURING"
    HEALTHCARE = "HEALTHCARE"
    CONSTRUCTION = "CONSTRUCTION"
    INFORMATION_TECHNOLOGY = "INFORMATION_TECHNOLOGY"
    HOSPITALITY = "HOSPITALITY"
    PUBLIC_ADMINISTRATION = "PUBLIC_ADMINISTRATION"


class EmployerPosture(str, Enum):
    PROSPECT = "PROSPECT"
    ELIGIBLE = "ELIGIBLE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class HazardClass(str, Enum):
    NON_HAZARDOUS = "NON_HAZARDOUS"
    LIMITED_HAZARD = "LIMITED_HAZARD"
    PROHIBITED_HAZARD = "PROHIBITED_HAZARD"


class WorksiteSafetyStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"


class SafetyReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class SafetyReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"


class AgreementStatus(str, Enum):
    PENDING_EMPLOYER = "PENDING_EMPLOYER"
    PENDING_DISTRICT = "PENDING_DISTRICT"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_GRADE = "INELIGIBLE_GRADE"
    INELIGIBLE_ACADEMIC = "INELIGIBLE_ACADEMIC"
    INELIGIBLE_ATTENDANCE = "INELIGIBLE_ATTENDANCE"


class PermitClass(str, Enum):
    MINOR_14_15 = "MINOR_14_15"
    MINOR_16_17 = "MINOR_16_17"
    ADULT_18_PLUS = "ADULT_18_PLUS"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PlacementLifecycleStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class PlacementComplianceStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    BLOCKED = "BLOCKED"


class ComplianceDecision(str, Enum):
    CLEAR = "CLEAR"
    FLAG = "FLAG"
    UNBLOCK = "UNBLOCK"


class PayClassification(str, Enum):
    PAID = "PAID"
    UNPAID = "UNPAID"
    STIPEND = "STIPEND"


class CreditAwardMode(str, Enum):
    HOURS_BASED = "HOURS_BASED"
    COMPETENCY_BASED = "COMPETENCY_BASED"


class TransportationMode(str, Enum):
    DISTRICT_BUS = "DISTRICT_BUS"
    PUBLIC_TRANSIT = "PUBLIC_TRANSIT"
    SELF = "SELF"
    GUARDIAN = "GUARDIAN"


class WageSettlementMode(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TrainingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class AssessmentMethod(str, Enum):
    SUPERVISOR_RATING = "SUPERVISOR_RATING"
    PORTFOLIO = "PORTFOLIO"
    EXAM = "EXAM"
    REFLECTION = "REFLECTION"


class TimesheetEntryStatus(str, Enum):
    LOGGED = "LOGGED"
    VOIDED = "VOIDED"


class SupervisorEvalStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"


class ReflectionStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class ReflectionDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    CRITICAL = "CRITICAL"


class InjuryType(str, Enum):
    NONE = "NONE"
    LACERATION = "LACERATION"
    FRACTURE = "FRACTURE"
    BURN = "BURN"
    STRAIN = "STRAIN"
    EXPOSURE = "EXPOSURE"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    CLOSED = "CLOSED"


class IncidentFinding(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class CoverageDetermination(str, Enum):
    PENDING = "PENDING"
    WORKERS_COMP = "WORKERS_COMP"
    DISTRICT_LIABILITY = "DISTRICT_LIABILITY"
    EMPLOYER_LIABILITY_UNINSURED = "EMPLOYER_LIABILITY_UNINSURED"
    NOT_COVERED = "NOT_COVERED"


class OutcomeType(str, Enum):
    EMPLOYED_FULL_TIME = "EMPLOYED_FULL_TIME"
    EMPLOYED_PART_TIME = "EMPLOYED_PART_TIME"
    POSTSECONDARY_ENROLLED = "POSTSECONDARY_ENROLLED"
    APPRENTICESHIP = "APPRENTICESHIP"
    MILITARY = "MILITARY"
    NOT_ENGAGED = "NOT_ENGAGED"
    UNKNOWN = "UNKNOWN"


class VerificationSource(str, Enum):
    EMPLOYER_LETTER = "EMPLOYER_LETTER"
    ENROLLMENT_RECORD = "ENROLLMENT_RECORD"
    STUDENT_ATTESTATION = "STUDENT_ATTESTATION"


class OutcomeStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    LATE_UNVERIFIABLE = "LATE_UNVERIFIABLE"


class ReimbursementTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------


class EmployerPartner(TypedDict):
    id: str
    legal_name: str
    naics_code: str
    industry_sector: str
    workers_comp_carrier: str
    workers_comp_policy_no: str
    workers_comp_expires_on: str
    safety_score: int
    posture: str
    substantiated_minor_count: int
    substantiated_moderate_count: int
    substantiated_critical_count: int
    wage_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class Worksite(TypedDict):
    id: str
    employer_partner_id: str
    site_name: str
    address_line: str
    hazard_class: str
    has_power_machinery: bool
    displaces_paid_employee: bool
    max_concurrent_students: int
    safety_status: str
    safety_review_expires_on: Optional[str]
    corrective_actions_due_on: Optional[str]
    slots_committed: int
    created_at: str
    updated_at: str
    version: int


class WorksiteSafetyReview(TypedDict):
    id: str
    worksite_id: str
    reviewer_user_id: str
    machinery_guarding_ok: bool
    hazard_findings_count: int
    orientation_documented: bool
    emergency_plan_on_file: bool
    status: str
    decision_on: Optional[str]
    corrective_actions_due_on: Optional[str]
    expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Supervisor(TypedDict):
    id: str
    worksite_id: str
    full_name: str
    email: str
    training_completed_on: str
    max_student_load: int
    active_student_load: int
    created_at: str
    updated_at: str
    version: int


class PartnershipAgreement(TypedDict):
    id: str
    employer_partner_id: str
    worksite_id: str
    employer_signer_supervisor_id: str
    effective_on: str
    expires_on: str
    insurance_rider: bool
    status: str
    revision_round: int
    created_by_user_id: str
    executed_by_user_id: Optional[str]
    executed_on: Optional[str]
    change_request_note: Optional[str]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    birth_date: str
    grade_level: int
    gpa: float
    attendance_rate: float
    student_learner_certificate: bool
    guardian_consent_on_file: bool
    eligibility_status: str
    ytd_wbl_hours: float
    credits_earned_wbl: float
    active_placement_count: int
    created_at: str
    updated_at: str
    version: int


class WorkPermit(TypedDict):
    id: str
    student_id: str
    permit_class: str
    hazardous_endorsement: bool
    status: str
    issued_on: Optional[str]
    expires_on: Optional[str]
    revoked_reason: Optional[str]
    issued_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    student_id: str
    worksite_id: str
    agreement_id: str
    supervisor_id: str
    supersedes_placement_id: Optional[str]
    scheduled_weekly_hours: float
    start_on: str
    end_on: str
    pay_classification: str
    hourly_wage_cents: int
    stipend_total_cents: int
    credit_target_credits: float
    credit_award_mode: str
    required_evaluation_cycles: int
    transportation_mode: str
    commute_round_trip_miles: float
    student_age_at_start: int
    permit_class_at_start: str
    lifecycle_status: str
    compliance_status: str
    total_verified_hours: float
    closed_cycle_count: int
    credit_eligible: bool
    provisional_wage_cents: int
    final_wage_cents: int
    settled_wage_cents: int
    wage_settlement_mode: str
    credits_awarded: float
    training_plan_approved_at: Optional[str]
    credit_awarded_by_user_id: Optional[str]
    completed_on: Optional[str]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingPlan(TypedDict):
    id: str
    placement_id: str
    course_code: str
    credit_hours_target: float
    status: str
    revision_round: int
    objective_count: int
    aligned_objective_count: int
    submitted_at: Optional[str]
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    change_request_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LearningObjective(TypedDict):
    """Append-only record: the PRD gives it only ``id`` and ``created_at``."""

    id: str
    training_plan_id: str
    competency_code: str
    description: str
    aligned_course_code: str
    assessment_method: str
    created_at: str


class TimesheetEntry(TypedDict):
    id: str
    placement_id: str
    work_date: str
    start_time: str
    end_time: str
    break_minutes: int
    is_school_day: bool
    hours_worked: float
    status: str
    voided_reason: Optional[str]
    voided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvaluationCycle(TypedDict):
    id: str
    placement_id: str
    cycle_index: int
    window_start: str
    window_end: str
    supervisor_eval_status: str
    reflection_status: str
    cycle_status: str
    rating_technical: Optional[int]
    rating_communication: Optional[int]
    rating_reliability: Optional[int]
    rating_safety: Optional[int]
    rating_initiative: Optional[int]
    competency_score: Optional[float]
    reflection_text: Optional[str]
    reflection_returned_count: int
    closed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    placement_id: str
    worksite_id: str
    reported_by_user_id: str
    occurred_at: str
    severity: str
    description: str
    injury_type: str
    status: str
    coverage_determination: str
    osha_recordable: bool
    determined_by_user_id: Optional[str]
    closed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlacementOutcome(TypedDict):
    id: str
    placement_id: str
    outcome_type: str
    employer_name: Optional[str]
    institution_name: Optional[str]
    verification_source: str
    status: str
    recorded_on: str
    verified_on: Optional[str]
    days_since_completion: int
    counts_positive: bool
    created_at: str
    updated_at: str
    version: int
