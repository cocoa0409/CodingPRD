"""Domain types for the Home and Hospital Instruction API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    CASE_MANAGER = "CaseManager"
    NURSE_REVIEWER = "NurseReviewer"
    HOMEBOUND_TEACHER = "HomeboundTeacher"
    CLASSROOM_TEACHER = "ClassroomTeacher"


# --------------------------------------------------------------------------
# Shared vocabularies
# --------------------------------------------------------------------------


class GradeBand(str, Enum):
    PRIMARY = "PRIMARY"
    MIDDLE = "MIDDLE"
    HIGH = "HIGH"


class DeliveryMode(str, Enum):
    IN_HOME = "IN_HOME"
    VIRTUAL_SYNC = "VIRTUAL_SYNC"
    HYBRID = "HYBRID"


class SessionDeliveryMode(str, Enum):
    IN_HOME = "IN_HOME"
    VIRTUAL_SYNC = "VIRTUAL_SYNC"


class Subject(str, Enum):
    MATH = "MATH"
    ELA = "ELA"
    SCIENCE = "SCIENCE"
    SOCIAL_STUDIES = "SOCIAL_STUDIES"
    GENERAL_ELEMENTARY = "GENERAL_ELEMENTARY"


class CredentialArea(str, Enum):
    MATH = "MATH"
    ELA = "ELA"
    SCIENCE = "SCIENCE"
    SOCIAL_STUDIES = "SOCIAL_STUDIES"
    GENERAL_ELEMENTARY = "GENERAL_ELEMENTARY"
    SPED = "SPED"


class DiagnosisCategory(str, Enum):
    MEDICAL_ACUTE = "MEDICAL_ACUTE"
    MEDICAL_CHRONIC = "MEDICAL_CHRONIC"
    PSYCHIATRIC = "PSYCHIATRIC"
    PREGNANCY_POSTPARTUM = "PREGNANCY_POSTPARTUM"
    INJURY_REHAB = "INJURY_REHAB"


# --------------------------------------------------------------------------
# Student
# --------------------------------------------------------------------------


class SpecialEdStatus(str, Enum):
    NONE = "NONE"
    IEP = "IEP"
    SECTION_504 = "SECTION_504"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


class Student(TypedDict):
    id: str
    student_number: str
    full_name: str
    grade_level: int
    grade_band: str
    campus_code: str
    special_ed_status: str
    iep_service_minutes_weekly: int
    enrollment_status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Teacher
# --------------------------------------------------------------------------


class TeacherClearanceStatus(str, Enum):
    CLEARED = "CLEARED"
    RESTRICTED = "RESTRICTED"
    EXPIRED = "EXPIRED"


class Teacher(TypedDict):
    id: str
    full_name: str
    employee_number: str
    credential_areas: List[str]
    grade_bands: List[str]
    max_weekly_caseload_minutes: int
    safety_clearance_status: str
    clearance_expires_on: str
    home_visit_eligible: bool
    committed_weekly_minutes: int
    over_cap: bool
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# EntitlementRule
# --------------------------------------------------------------------------


class EntitlementRuleStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class EntitlementRule(TypedDict):
    id: str
    grade_band: str
    delivery_mode: str
    base_weekly_minutes: int
    cap_weekly_minutes: int
    min_session_minutes: int
    max_session_minutes: int
    max_daily_minutes: int
    min_gap_minutes: int
    travel_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# HomeboundCase — two parallel status dimensions (PRD §2.9)
# --------------------------------------------------------------------------


class CaseServiceStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CERT_REVIEW = "PENDING_CERT_REVIEW"
    ELIGIBLE = "ELIGIBLE"
    ACTIVE = "ACTIVE"
    EXTENSION_PENDING = "EXTENSION_PENDING"
    TRANSITION_PLANNED = "TRANSITION_PLANNED"
    CLOSED = "CLOSED"
    DENIED = "DENIED"


class CaseFundingStatus(str, Enum):
    NOT_REPORTED = "NOT_REPORTED"
    ACCRUING = "ACCRUING"
    HELD = "HELD"
    RECONCILED = "RECONCILED"
    FORFEITED = "FORFEITED"


class CloseReason(str, Enum):
    WITHDRAWN = "WITHDRAWN"
    CERT_EXPIRED = "CERT_EXPIRED"
    DENIED_ELIGIBILITY = "DENIED_ELIGIBILITY"
    ADMIN_CLOSURE = "ADMIN_CLOSURE"
    RETURNED_TO_CAMPUS = "RETURNED_TO_CAMPUS"


class HomeboundCase(TypedDict):
    id: str
    student_id: str
    referral_date: str
    delivery_mode: str
    referral_note: Optional[str]
    service_status: str
    funding_status: str
    entitlement_rule_id: Optional[str]
    diagnosis_category: Optional[str]
    certified_start_date: Optional[str]
    certified_end_date: Optional[str]
    weekly_entitled_minutes: int
    service_start_date: Optional[str]
    escort_required: bool
    certification_count: int
    extension_count: int
    reported_apportionment_minutes: int
    provisional_apportionment_minutes: int
    final_apportionment_minutes: int
    recapture_minutes: int
    net_apportionment_minutes: int
    delivery_ratio_pct: float
    service_gap_minutes: int
    makeup_obligation_minutes: int
    close_reason: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# PhysicianCertification
# --------------------------------------------------------------------------


class CertificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class PhysicianCertification(TypedDict):
    id: str
    case_id: str
    physician_npi: str
    diagnosis_category: str
    certified_start_date: str
    certified_end_date: str
    expected_absence_days: int
    signature_date: str
    clinical_note: Optional[str]
    status: str
    is_current: bool
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# TeacherAssignment
# --------------------------------------------------------------------------


class AssignmentRole(str, Enum):
    PRIMARY = "PRIMARY"
    SUPPORT = "SUPPORT"
    SPED_SERVICE = "SPED_SERVICE"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"


class ReleaseReason(str, Enum):
    CASE_CLOSED = "CASE_CLOSED"
    MODE_CHANGE = "MODE_CHANGE"
    CASELOAD_REBALANCE = "CASELOAD_REBALANCE"
    CLEARANCE_LAPSED = "CLEARANCE_LAPSED"
    STAFF_LEAVE = "STAFF_LEAVE"


class TeacherAssignment(TypedDict):
    id: str
    case_id: str
    teacher_id: str
    role: str
    status: str
    weekly_committed_minutes: int
    accepted_at: Optional[str]
    released_at: Optional[str]
    release_reason: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# HomeVisitSafetyReview
# --------------------------------------------------------------------------


class EvidenceSource(str, Enum):
    PARENT_ATTESTATION = "PARENT_ATTESTATION"
    ONSITE_WALKTHROUGH = "ONSITE_WALKTHROUGH"


class ScoringVariant(str, Enum):
    SELF_REPORTED = "SELF_REPORTED"
    ONSITE_VERIFIED = "ONSITE_VERIFIED"


class HazardFinding(str, Enum):
    AGGRESSIVE_ANIMAL = "AGGRESSIVE_ANIMAL"
    NO_SECONDARY_EXIT = "NO_SECONDARY_EXIT"
    WEAPON_PRESENT_UNSECURED = "WEAPON_PRESENT_UNSECURED"
    SMOKE_OR_AIR_QUALITY = "SMOKE_OR_AIR_QUALITY"
    ACTIVE_INFECTION_RISK = "ACTIVE_INFECTION_RISK"
    UNLIT_ACCESS = "UNLIT_ACCESS"
    NO_ADULT_PRESENT = "NO_ADULT_PRESENT"


class SafetyReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class SafetyClearance(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    CLEARED_WITH_ESCORT = "CLEARED_WITH_ESCORT"
    VIRTUAL_ONLY = "VIRTUAL_ONLY"
    BLOCKED = "BLOCKED"


class HomeVisitSafetyReview(TypedDict):
    id: str
    case_id: str
    evidence_source: str
    scoring_variant: str
    review_date: str
    hazard_findings: List[str]
    escort_available: bool
    risk_score: int
    clearance: str
    status: str
    expires_on: str
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# InstructionSession
# --------------------------------------------------------------------------


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    STUDENT_UNAVAILABLE = "STUDENT_UNAVAILABLE"
    TEACHER_CANCELLED = "TEACHER_CANCELLED"
    SAFETY_ABORTED = "SAFETY_ABORTED"
    CANCELLED_ADMIN = "CANCELLED_ADMIN"
    VOIDED = "VOIDED"


class SessionOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    STUDENT_UNAVAILABLE = "STUDENT_UNAVAILABLE"
    TEACHER_CANCELLED = "TEACHER_CANCELLED"
    SAFETY_ABORTED = "SAFETY_ABORTED"


class AbsenceKind(str, Enum):
    MEDICAL = "MEDICAL"
    UNEXCUSED = "UNEXCUSED"


class VoidReason(str, Enum):
    DOCUMENTATION_DEFECT = "DOCUMENTATION_DEFECT"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    AUDIT_REVERSAL = "AUDIT_REVERSAL"
    MODE_INELIGIBLE = "MODE_INELIGIBLE"


class InstructionSession(TypedDict):
    id: str
    case_id: str
    assignment_id: str
    scheduled_start: str
    scheduled_end: str
    scheduled_minutes: int
    service_date: str
    delivery_mode: str
    subject: str
    escort_confirmed: bool
    status: str
    actual_minutes: Optional[int]
    credited_minutes: int
    absence_kind: Optional[str]
    outcome_reason: Optional[str]
    makeup_for_session_id: Optional[str]
    void_reason: Optional[str]
    logged_by_user_id: Optional[str]
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# AttendanceLedgerEntry — append-only: carries only id and created_at
# (PRD §2.5: "both `updated_at` and `version` are absent from an
# `AttendanceLedgerEntry` entirely.")
# --------------------------------------------------------------------------


class AttendanceCode(str, Enum):
    HB_PRESENT = "HB_PRESENT"
    HB_VIRTUAL_PRESENT = "HB_VIRTUAL_PRESENT"
    HB_ABSENT_MEDICAL = "HB_ABSENT_MEDICAL"
    HB_ABSENT_UNEXCUSED = "HB_ABSENT_UNEXCUSED"
    HB_NOT_SERVED = "HB_NOT_SERVED"
    HB_REVERSAL = "HB_REVERSAL"


class AttendanceLedgerEntry(TypedDict):
    id: str
    case_id: str
    session_id: str
    attendance_code: str
    apportionment_minutes: int
    service_date: str
    delivery_mode: str
    reversal_of_entry_id: Optional[str]
    recorded_by_user_id: str
    created_at: str
    # NO updated_at, NO version — append-only ledger row.


# --------------------------------------------------------------------------
# ExtensionRequest
# --------------------------------------------------------------------------


class ExtensionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ExtensionDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ExtensionRequest(TypedDict):
    id: str
    case_id: str
    certification_id: str
    requested_additional_days: int
    justification: str
    status: str
    resubmit_count: int
    info_note: Optional[str]
    decision_note: Optional[str]
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# TransitionPlan
# --------------------------------------------------------------------------


class ReintegrationMode(str, Enum):
    FULL_DAY = "FULL_DAY"
    PARTIAL_DAY_RAMP = "PARTIAL_DAY_RAMP"
    VIRTUAL_BRIDGE = "VIRTUAL_BRIDGE"


class TransitionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    CLASSROOM_COORD_PENDING = "CLASSROOM_COORD_PENDING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    SUPERSEDED = "SUPERSEDED"


class AbortReason(str, Enum):
    MEDICAL_RELAPSE = "MEDICAL_RELAPSE"
    PARENT_WITHDRAWAL = "PARENT_WITHDRAWAL"
    CAMPUS_CAPACITY = "CAMPUS_CAPACITY"
    DOCUMENTATION_DEFECT = "DOCUMENTATION_DEFECT"


class TransitionPlan(TypedDict):
    id: str
    case_id: str
    target_return_date: str
    reintegration_mode: str
    ramp_weeks: int
    status: str
    required_ack_count: int
    classroom_ack_count: int
    completed_at: Optional[str]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# CurriculumPacingSync
# --------------------------------------------------------------------------


class AssessmentAccommodation(str, Enum):
    NONE = "NONE"
    EXTENDED_TIME = "EXTENDED_TIME"
    ORAL_ADMINISTRATION = "ORAL_ADMINISTRATION"
    ALTERNATE_SETTING_PROCTOR = "ALTERNATE_SETTING_PROCTOR"


class PacingAckStatus(str, Enum):
    PENDING = "PENDING"
    ACKED = "ACKED"
    DISPUTED = "DISPUTED"


class CurriculumPacingSync(TypedDict):
    id: str
    case_id: str
    classroom_teacher_id: str
    subject: str
    pacing_target_unit: str
    assessment_accommodation: str
    ack_status: str
    acked_at: Optional[str]
    dispute_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# SpedServiceLog
# --------------------------------------------------------------------------


class SpedServiceType(str, Enum):
    SPEECH = "SPEECH"
    OT = "OT"
    PT = "PT"
    COUNSELING = "COUNSELING"
    SPECIALIZED_ACADEMIC = "SPECIALIZED_ACADEMIC"


class SpedContinuationStatus(str, Enum):
    CONTINUED = "CONTINUED"
    MODIFIED_VIRTUAL = "MODIFIED_VIRTUAL"
    SUSPENDED_PENDING_IEP = "SUSPENDED_PENDING_IEP"


class SpedServiceLog(TypedDict):
    id: str
    case_id: str
    service_type: str
    required_weekly_minutes: int
    continuation_status: str
    continuation_reason: Optional[str]
    delivered_cumulative_minutes: int
    last_service_date: Optional[str]
    compensatory_minutes_owed: int
    created_at: str
    updated_at: str
    version: int
