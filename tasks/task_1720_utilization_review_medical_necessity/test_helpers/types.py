"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4-§2.6, §3).

All primary resources carry id / created_at / updated_at / version (PRD §2.6).
AuditEvent is the single append-only exception: id and created_at only.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    UR_NURSE = "URNurse"
    ATTENDING_PHYSICIAN = "AttendingPhysician"
    PHYSICIAN_ADVISOR = "PhysicianAdvisor"
    PAYER_REVIEWER = "PayerReviewer"
    CASE_MANAGER = "CaseManager"
    APPEALS_COORDINATOR = "AppealsCoordinator"
    UR_DIRECTOR = "URDirector"


class PlanClass(str, Enum):
    MEDICARE = "MEDICARE"
    MANAGED_MEDICARE = "MANAGED_MEDICARE"
    MEDICAID = "MEDICAID"
    COMMERCIAL = "COMMERCIAL"


class AttributionMethod(str, Enum):
    FIRST_CAUSE = "FIRST_CAUSE"
    DOMINANT_CAUSE = "DOMINANT_CAUSE"


class AdmissionStatus(str, Enum):
    INPATIENT = "INPATIENT"
    OBSERVATION = "OBSERVATION"


class ReviewStatus(str, Enum):
    INTAKE = "INTAKE"
    ADMISSION_REVIEWED = "ADMISSION_REVIEWED"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"


class AuthStatus(str, Enum):
    AUTH_PENDING = "AUTH_PENDING"
    AUTH_IN_PROGRESS = "AUTH_IN_PROGRESS"
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"


class BenchmarkMet(str, Enum):
    MET = "MET"
    NOT_MET = "NOT_MET"


class BenchmarkBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class CriteriaSet(str, Enum):
    INTERQUAL = "INTERQUAL"
    MCG = "MCG"


class ReviewDetermination(str, Enum):
    PENDING = "PENDING"
    CRITERIA_MET = "CRITERIA_MET"
    CRITERIA_NOT_MET = "CRITERIA_NOT_MET"


class AdmissionReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADVISOR_REVIEWED = "ADVISOR_REVIEWED"


class AuthRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDED = "PENDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class DenialReasonCode(str, Enum):
    CRITERIA_NOT_MET = "CRITERIA_NOT_MET"
    DOC_INSUFFICIENT = "DOC_INSUFFICIENT"
    LEVEL_OF_CARE = "LEVEL_OF_CARE"


class ConcurrentReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"


class ConferenceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ConferenceOutcome(str, Enum):
    NONE = "NONE"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class Cc44Status(str, Enum):
    CONCURRENCE_PENDING = "CONCURRENCE_PENDING"
    COMMITTEE_PENDING = "COMMITTEE_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DECLINED_CLOSED = "DECLINED_CLOSED"
    RESCINDED = "RESCINDED"


class Concurrence(str, Enum):
    PENDING = "PENDING"
    CONCURRED = "CONCURRED"
    DECLINED = "DECLINED"


class BarrierCode(str, Enum):
    PLACEMENT_DELAY = "PLACEMENT_DELAY"
    PAYER_AUTH_DELAY = "PAYER_AUTH_DELAY"
    TRANSPORT_DELAY = "TRANSPORT_DELAY"
    FAMILY_DECISION = "FAMILY_DECISION"
    PHYSICIAN_DELAY = "PHYSICIAN_DELAY"


class AvoidableDayStatus(str, Enum):
    OPEN = "OPEN"
    MITIGATED = "MITIGATED"
    OVERTURNED = "OVERTURNED"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class DenialType(str, Enum):
    INITIAL_AUTH = "INITIAL_AUTH"
    CONCURRENT = "CONCURRENT"


class DenialStatus(str, Enum):
    OPEN = "OPEN"
    P2P_SCHEDULED = "P2P_SCHEDULED"
    APPEAL_FILED = "APPEAL_FILED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_OVERTURNED = "RESOLVED_OVERTURNED"
    RESOLVED_PARTIAL = "RESOLVED_PARTIAL"
    CLOSED_NO_APPEAL = "CLOSED_NO_APPEAL"


class AppealStatus(str, Enum):
    FILED = "FILED"
    DECIDED_UPHELD = "DECIDED_UPHELD"
    DECIDED_OVERTURNED = "DECIDED_OVERTURNED"
    DECIDED_PARTIAL = "DECIDED_PARTIAL"


class Payer(TypedDict, total=False):
    id: str
    name: str
    plan_class: str
    requires_inpatient_auth: bool
    concurrent_review_cadence_hours: int
    p2p_window_hours: int
    appeal_deadline_days: int
    bed_day_budget_per_case: int
    avoidable_attribution_method: str
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict, total=False):
    id: str
    full_name: str
    specialty: str
    is_advisor: bool
    created_at: str
    updated_at: str
    version: int


class UtilizationCase(TypedDict, total=False):
    id: str
    patient_mrn: str
    payer_id: str
    attending_physician_id: str
    admit_at: str
    expected_discharge_at: str
    discharge_at: Optional[str]
    requested_admission_status: str
    current_admission_status: str
    review_status: str
    auth_status: str
    expected_midnight_count: int
    actual_midnight_count: Optional[int]
    two_midnight_benchmark_met: str
    benchmark_basis: str
    certified_day_count: int
    certified_inpatient_day_count: int
    certified_observation_day_count: int
    open_avoidable_day_count: int
    escalation_tier: int
    created_at: str
    updated_at: str
    version: int


class AdmissionReview(TypedDict, total=False):
    id: str
    case_id: str
    criteria_set: str
    severity_of_illness_points: int
    intensity_of_service_points: int
    comorbidity_count: int
    two_midnight_attestation: bool
    necessity_score: Optional[int]
    determination: str
    recommended_status: Optional[str]
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuthorizationRequest(TypedDict, total=False):
    id: str
    case_id: str
    level_of_care: str
    requested_day_count: int
    clinical_summary: str
    submission_round: int
    status: str
    certified_day_start: Optional[int]
    certified_day_end: Optional[int]
    denial_reason_code: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConcurrentReview(TypedDict, total=False):
    id: str
    authorization_request_id: str
    sequence_index: int
    clinical_update: str
    requested_additional_day_count: int
    review_due_at: str
    submitted_at: str
    status: str
    approved_day_count: Optional[int]
    certified_day_start: Optional[int]
    certified_day_end: Optional[int]
    decided_at: Optional[str]
    denial_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PeerToPeerConference(TypedDict, total=False):
    id: str
    authorization_request_id: str
    attending_physician_id: str
    advisor_physician_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    window_deadline_at: str
    reschedule_count: int
    status: str
    outcome: str
    created_at: str
    updated_at: str
    version: int


class Cc44ServiceLine(TypedDict):
    description: str
    charge_cents: int
    rate_milli: int


class ConditionCode44Request(TypedDict, total=False):
    id: str
    case_id: str
    rationale: str
    service_lines: List[Cc44ServiceLine]
    rebill_estimate_cents: int
    attending_concurrence: str
    committee_reviewer_id: Optional[str]
    status: str
    effective_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AvoidableDay(TypedDict, total=False):
    id: str
    case_id: str
    day_date: str
    barrier_code: str
    barrier_weight: int
    is_attributed: bool
    status: str
    mitigation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscalationCase(TypedDict, total=False):
    id: str
    case_id: str
    tier: int
    trigger_open_day_count: int
    director_credit_days: int
    effective_tier: int
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DenialCase(TypedDict, total=False):
    id: str
    case_id: str
    authorization_request_id: str
    denial_type: str
    denied_at: str
    denied_day_count: int
    appeal_deadline_at: str
    denial_is_final: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AppealCase(TypedDict, total=False):
    id: str
    denial_id: str
    appeal_level: int
    argument_summary: str
    filed_at: str
    status: str
    decided_at: Optional[str]
    overturned_day_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict, total=False):
    # Append-only resource (PRD §2.6): carries id and created_at only;
    # both updated_at and version are absent.
    id: str
    case_id: str
    event_type: str
    actor_role: str
    actor_id: str
    payload_summary: str
    created_at: str
