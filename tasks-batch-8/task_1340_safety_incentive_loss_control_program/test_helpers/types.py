"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    EHS_ADMIN = "EHSAdmin"
    SAFETY_MANAGER = "SafetyManager"
    SUPERVISOR = "Supervisor"
    EMPLOYEE = "Employee"
    COMMITTEE_CHAIR = "CommitteeChair"
    CONTRACTOR_REP = "ContractorRep"
    CARRIER_CONSULTANT = "CarrierConsultant"


class ScoringVariant(str, Enum):
    LEADING_ONLY = "LEADING_ONLY"
    BALANCED = "BALANCED"


class HazardClass(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class Posture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TrainingAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class TrainingSource(str, Enum):
    SYSTEM_JOB_HAZARD = "SYSTEM_JOB_HAZARD"
    MANUAL = "MANUAL"


class HazardStatus(str, Enum):
    OPEN = "OPEN"
    ASSESSED = "ASSESSED"
    CONTROLS_PLANNED = "CONTROLS_PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    CLOSED = "CLOSED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ControlStatus(str, Enum):
    PLANNED = "PLANNED"
    OVERDUE = "OVERDUE"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"


class ObservationKind(str, Enum):
    OBSERVATION = "OBSERVATION"
    NEAR_MISS = "NEAR_MISS"


class ObservationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    LINKED = "LINKED"
    NO_ACTION = "NO_ACTION"
    CLOSED = "CLOSED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    MINUTES_PUBLISHED = "MINUTES_PUBLISHED"
    CANCELLED = "CANCELLED"


class ActionItemStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    ESCALATED = "ESCALATED"


class ContractorStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class ComputedDecision(str, Enum):
    APPROVE = "APPROVE"
    CONDITIONAL = "CONDITIONAL"
    REJECT = "REJECT"


class ClaimKind(str, Enum):
    MEDICAL_ONLY = "MEDICAL_ONLY"
    INDEMNITY = "INDEMNITY"


class ClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class RecommendationPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RecommendationStatus(str, Enum):
    ISSUED = "ISSUED"
    OVERDUE = "OVERDUE"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    CARRIER_REJECTED = "CARRIER_REJECTED"
    CLOSED_ACCEPTED = "CLOSED_ACCEPTED"


class AwardTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class AwardStatus(str, Enum):
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class EventSourceType(str, Enum):
    OBSERVATION_VALIDATED = "OBSERVATION_VALIDATED"
    NEAR_MISS_VALIDATED = "NEAR_MISS_VALIDATED"
    CONTROL_VERIFIED = "CONTROL_VERIFIED"
    ACTION_VERIFIED = "ACTION_VERIFIED"
    MEETING_ATTENDED = "MEETING_ATTENDED"
    CLAIMS_FREE_BONUS = "CLAIMS_FREE_BONUS"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class SafetyProgram(TypedDict, total=False):
    id: str
    program_year: int
    scoring_variant: str
    incentive_budget_cents: int
    remaining_budget_cents: int
    observation_target_rate: float
    near_miss_floor_ratio: float
    quorum_min: int
    exposure_hours: int
    payroll_by_class: List[dict]
    elr_by_class: List[dict]
    status: str
    posture: str
    overdue_control_count: int
    sla_breach_count: int
    integrity_flag: bool
    sweep_index: int
    created_at: str
    updated_at: str
    version: int


class JobRole(TypedDict, total=False):
    id: str
    title: str
    hazard_class: str
    required_course_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class TrainingCourse(TypedDict, total=False):
    id: str
    title: str
    hazard_class: str
    validity_months: int
    renewal_window_days: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    full_name: str
    job_role_id: str
    hired_on: str
    committee_member: bool
    status: str
    pending_required_training_count: int
    created_at: str
    updated_at: str
    version: int


class TrainingAssignment(TypedDict, total=False):
    id: str
    employee_id: str
    course_id: str
    due_date: str
    required: bool
    source: str
    status: str
    completed_at: Optional[str]
    cert_valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hazard(TypedDict, total=False):
    id: str
    program_id: str
    location: str
    description: str
    identified_by: str
    severity: Optional[int]
    probability: Optional[int]
    risk_score: Optional[int]
    risk_band: Optional[str]
    response_sla_due: Optional[str]
    sla_breached: bool
    overdue_control_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ControlItem(TypedDict, total=False):
    id: str
    hazard_id: str
    description: str
    implementer_id: str
    due_date: str
    implemented_at: Optional[str]
    verified_by: Optional[str]
    verified_at: Optional[str]
    outcome_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Observation(TypedDict, total=False):
    id: str
    program_id: str
    reporter_id: str
    kind: str
    description: str
    occurred_at: str
    linked_hazard_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitteeMeeting(TypedDict, total=False):
    id: str
    program_id: str
    scheduled_start: str
    scheduled_end: str
    location: str
    attendee_ids: Optional[List[str]]
    minutes_text: Optional[str]
    open_action_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ActionItem(TypedDict, total=False):
    id: str
    meeting_id: str
    assignee_id: str
    description: str
    due_date: str
    hazard_id: Optional[str]
    completed_at: Optional[str]
    verified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractorOrg(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    emr: float
    trir: float
    safety_audit_pct: float
    insurance_cert_expires_on: str
    prequal_score: Optional[float]
    computed_decision: Optional[str]
    status: str
    prequal_valid_until: Optional[str]
    suspension_reason: Optional[str]
    suspension_claim_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimRecord(TypedDict, total=False):
    id: str
    program_id: str
    employee_id: Optional[str]
    contractor_org_id: Optional[str]
    occurred_on: str
    kind: str
    incurred_cents: int
    effective_incurred_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LossControlRecommendation(TypedDict, total=False):
    id: str
    program_id: str
    carrier_name: str
    priority: str
    description: str
    due_date: str
    response_text: Optional[str]
    evidence_control_id: Optional[str]
    responded_by: Optional[str]
    reviewed_by: Optional[str]
    review_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IncentiveAward(TypedDict, total=False):
    id: str
    program_id: str
    employee_id: str
    points_earned: int
    tier: str
    payout_cents: int
    void_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only point-ledger entry: carries ONLY id + created_at (no updated_at,
# no version).
class IncentiveEvent(TypedDict, total=False):
    id: str
    program_id: str
    employee_id: str
    source_type: str
    points_base: int
    hazard_class_multiplier: float
    timeliness_multiplier: float
    points_awarded: int
    reference_id: str
    created_at: str


# Immutable valuation snapshot: carries ONLY id + created_at (no updated_at,
# no version).
class EMRForecast(TypedDict, total=False):
    id: str
    program_id: str
    as_of: str
    payroll_factor: float
    expected_losses_provisional_cents: int
    expected_losses_final_cents: int
    weighting_w: float
    ballast_provisional_cents: int
    ballast_final_cents: int
    actual_primary_provisional_cents: int
    actual_excess_provisional_cents: int
    actual_primary_final_cents: int
    actual_excess_final_cents: int
    emr_provisional: float
    emr_final: float
    created_at: str
