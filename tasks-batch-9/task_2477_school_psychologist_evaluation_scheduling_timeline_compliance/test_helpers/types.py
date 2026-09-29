"""Domain types for the School Psych Evaluation Timeline API.

Every one of the eleven persisted resource types carries the same four
system-managed properties — `id`, `created_at`, `updated_at` and `version` — so
every TypedDict below lists all four.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    SCHOOL_PSYCHOLOGIST = "SchoolPsychologist"
    PSYCH_SERVICES_SUPERVISOR = "PsychServicesSupervisor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    DISTRICT_ADMIN = "DistrictAdmin"


class GradeBand(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    MIDDLE = "MIDDLE"
    HIGH = "HIGH"


class CredentialType(str, Enum):
    SSP = "SSP"
    PHD = "PHD"
    INTERN = "INTERN"


class PsychologistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"


class CaseloadStatus(str, Enum):
    BALANCED = "BALANCED"
    AT_CAP = "AT_CAP"
    OVER_CAP = "OVER_CAP"


class ReferralType(str, Enum):
    INITIAL = "INITIAL"
    REEVALUATION = "REEVALUATION"


class ReferralStatus(str, Enum):
    INTAKE_RECEIVED = "INTAKE_RECEIVED"
    CONSENTED = "CONSENTED"
    CONSENT_WAIVED = "CONSENT_WAIVED"
    CONSENT_WITHDRAWN = "CONSENT_WITHDRAWN"
    COMPLETED = "COMPLETED"


class ConsentEventType(str, Enum):
    CONSENT_RECEIVED = "CONSENT_RECEIVED"
    CONSENT_WAIVED = "CONSENT_WAIVED"
    CONSENT_WITHDRAWN = "CONSENT_WITHDRAWN"


class AssessmentDomain(str, Enum):
    COGNITIVE = "COGNITIVE"
    ACADEMIC = "ACADEMIC"
    SOCIAL_EMOTIONAL = "SOCIAL_EMOTIONAL"
    ADAPTIVE = "ADAPTIVE"


class AssessmentStatus(str, Enum):
    PENDING_ASSIGNMENT = "PENDING_ASSIGNMENT"
    ASSIGNED = "ASSIGNED"
    IN_TESTING = "IN_TESTING"
    SCORED = "SCORED"
    REPORT_DRAFTED = "REPORT_DRAFTED"
    REPORT_FINAL = "REPORT_FINAL"
    CANCELLED = "CANCELLED"


class ComplianceStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"
    COMPLIANT_CLOSED = "COMPLIANT_CLOSED"
    BREACH_CLOSED_REMEDIED = "BREACH_CLOSED_REMEDIED"
    WAIVED = "WAIVED"


class ExclusionType(str, Enum):
    BREAK_CLOSURE = "BREAK_CLOSURE"
    PARENT_UNAVAILABLE = "PARENT_UNAVAILABLE"
    STUDENT_ABSENT_STREAK = "STUDENT_ABSENT_STREAK"
    TRANSFER_IN_TRANSIT = "TRANSFER_IN_TRANSIT"


class ExclusionStatus(str, Enum):
    CLAIMED = "CLAIMED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExclusionDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class SeatStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"
    RECEIVED = "RECEIVED"


class OrderDecision(str, Enum):
    APPROVE = "APPROVE"
    CANCEL = "CANCEL"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CancellationReason(str, Enum):
    PSYCHOLOGIST_UNAVAILABLE = "PSYCHOLOGIST_UNAVAILABLE"
    CONSENT_WITHDRAWN = "CONSENT_WITHDRAWN"


class MeetingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    NOTICED = "NOTICED"
    RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED"
    HELD = "HELD"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class BreachStatus(str, Enum):
    DETECTED = "DETECTED"
    REMEDY_PROPOSED = "REMEDY_PROPOSED"
    REMEDY_APPROVED = "REMEDY_APPROVED"
    VACATED = "VACATED"


class BreachSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class RemedyBasis(str, Enum):
    BREACH_DAY_BASIS = "BREACH_DAY_BASIS"
    MISSED_SERVICE_BASIS = "MISSED_SERVICE_BASIS"


class ReportReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"


OPEN_ASSESSMENT_STATUSES = (
    AssessmentStatus.ASSIGNED.value,
    AssessmentStatus.IN_TESTING.value,
    AssessmentStatus.SCORED.value,
    AssessmentStatus.REPORT_DRAFTED.value,
)

CLOSED_COMPLIANCE_STATUSES = (
    ComplianceStatus.COMPLIANT_CLOSED.value,
    ComplianceStatus.BREACH_CLOSED_REMEDIED.value,
    ComplianceStatus.WAIVED.value,
)


class School(TypedDict):
    id: str
    name: str
    building_code: str
    grade_band: str
    concurrent_meeting_capacity: int
    enrollment_count: int
    created_at: str
    updated_at: str
    version: int


class Psychologist(TypedDict):
    id: str
    full_name: str
    employee_number: str
    credential_type: str
    languages_certified: List[str]
    assigned_school_ids: List[str]
    weekly_capacity_points: int
    status: str
    open_case_points: int
    caseload_status: str
    pressure_index_assigned_basis: float
    pressure_index_clock_weighted: float
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    school_id: str
    active_evaluation_id: Optional[str]
    student_local_id: str
    referral_type: str
    prior_evaluation_id: Optional[str]
    primary_language: str
    interpreter_required: bool
    bilingual_evaluation_required: bool
    requested_domains: List[str]
    intervention_team_summary: str
    status: str
    consent_received_at: Optional[str]
    last_consent_event_type: Optional[str]
    parent_signature_reference: Optional[str]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict):
    id: str
    referral_id: str
    psychologist_id: Optional[str]
    prior_evaluation_id: Optional[str]
    testing_instrument_id: Optional[str]
    report_drafted_by_psychologist_id: Optional[str]
    evaluation_domains: List[str]
    interpreter_required: bool
    referral_type: str
    assessment_status: str
    compliance_status: str
    clock_start_date: str
    base_due_date: str
    credited_exclusion_days: int
    statutory_due_date: str
    elapsed_statutory_days: int
    days_remaining: int
    caseload_points: int
    reassignment_count: int
    protocol_units_consumed: int
    score_summary: Optional[str]
    report_narrative: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TimelineExclusion(TypedDict):
    id: str
    evaluation_id: str
    exclusion_type: str
    start_date: str
    end_date: str
    claim_note: str
    status: str
    days_claimed: int
    days_credited: int
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssessmentInstrument(TypedDict):
    id: str
    name: str
    instrument_code: str
    protocol_stock_count: int
    protocol_units_per_administration: int
    protocol_unit_cost_cents: int
    license_seat_total: int
    license_seats_free: int
    license_expires_on: str
    license_status: str
    supported_language_editions: List[str]
    created_at: str
    updated_at: str
    version: int


class ProtocolOrder(TypedDict):
    id: str
    instrument_id: str
    quantity_requested: int
    rush_flag: bool
    unit_price_cents: int
    base_cents: int
    contract_discount_cents: int
    rush_surcharge_cents: int
    handling_fee_cents: int
    total_cost_cents: int
    status: str
    auto_approved: bool
    received_quantity: int
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScoringLicenseSeat(TypedDict):
    id: str
    instrument_id: str
    psychologist_id: str
    status: str
    assigned_at: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterpreterSession(TypedDict):
    id: str
    evaluation_id: str
    language_code: str
    interpreter_name: str
    session_start_at: str
    session_end_at: str
    status: str
    cancellation_reason: Optional[str]
    duration_minutes: int
    created_at: str
    updated_at: str
    version: int


class EligibilityMeeting(TypedDict):
    id: str
    evaluation_id: str
    school_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    parent_notice_sent_at: Optional[str]
    notice_lead_days: Optional[int]
    reschedule_count: int
    status: str
    held_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TimelineBreach(TypedDict):
    id: str
    evaluation_id: str
    detected_at: str
    breach_days: int
    severity: str
    minutes_breach_day_basis: int
    minutes_missed_service_basis: int
    remedy_basis: Optional[str]
    additional_minutes: int
    remedy_minutes_awarded: int
    corrective_action_note: Optional[str]
    proposed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceRunSummary(TypedDict):
    run_at: str
    evaluated_count: int
    at_risk_evaluation_ids: List[str]
    breached_evaluation_ids: List[str]
    breach_ids: List[str]
    sessions_completed_count: int
