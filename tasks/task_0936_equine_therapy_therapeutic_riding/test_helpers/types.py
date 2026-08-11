"""Domain types: entity TypedDicts, status enums and the role enum.

Field lists follow PRD 2.4: every resource carries `id` and `created_at`; all of
them except `ConditionPolicy` additionally carry `updated_at` and `version`.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INSTRUCTOR = "Instructor"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    BILLING_CLERK = "BillingClerk"


class RiderStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    MEDICAL_HOLD = "MEDICAL_HOLD"
    WITHDRAWN = "WITHDRAWN"


class AssessmentStatusAxis(str, Enum):
    NEVER_ASSESSED = "NEVER_ASSESSED"
    CURRENT = "CURRENT"
    DUE = "DUE"
    OVERDUE = "OVERDUE"


class AssessmentStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"


class IndependenceLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    LEVEL_4 = "LEVEL_4"


class MedicalReleaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class HorseStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    VET_HOLD = "VET_HOLD"
    FARRIER_HOLD = "FARRIER_HOLD"
    REST_HOLD = "REST_HOLD"


class VolunteerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class QualificationStatus(str, Enum):
    IN_TRAINING = "IN_TRAINING"
    QUALIFIED = "QUALIFIED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class CertificationStatus(str, Enum):
    CURRENT = "CURRENT"
    GRACE = "GRACE"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"


class CertificationLevel(str, Enum):
    IN_TRAINING = "IN_TRAINING"
    REGISTERED = "REGISTERED"
    ADVANCED = "ADVANCED"
    MASTER = "MASTER"


class ScheduleStatus(str, Enum):
    CREW_PENDING = "CREW_PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    CHARGED = "CHARGED"
    FUNDED = "FUNDED"
    REVERSED = "REVERSED"


class CrewAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class CrewRole(str, Enum):
    LEADER = "LEADER"
    SIDEWALKER = "SIDEWALKER"
    BARN = "BARN"


class HoldType(str, Enum):
    NO_CONTACT = "NO_CONTACT"
    ARM_OVER_THIGH = "ARM_OVER_THIGH"
    THIGH_HOLD = "THIGH_HOLD"
    OVER_THE_THIGH = "OVER_THE_THIGH"
    ANKLE_HOLD = "ANKLE_HOLD"


class GoalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MET = "MET"
    STALE = "STALE"
    DISCONTINUED = "DISCONTINUED"


class ProgressNoteStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    AMENDED = "AMENDED"


class GrantStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"


class ScholarshipAwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    SUPERSEDED = "SUPERSEDED"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    FUNDED = "FUNDED"
    REVERSED = "REVERSED"


class ChargeType(str, Enum):
    SESSION_FEE = "SESSION_FEE"
    LATE_CANCELLATION_FEE = "LATE_CANCELLATION_FEE"
    NO_SHOW_FEE = "NO_SHOW_FEE"


class SourceType(str, Enum):
    GRANT = "GRANT"
    SCHOLARSHIP = "SCHOLARSHIP"
    SLIDING_SCALE = "SLIDING_SCALE"
    PAYER = "PAYER"
    PRIVATE_PAY = "PRIVATE_PAY"


class AllocationStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    RELEASED = "RELEASED"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class IncidentSeverity(str, Enum):
    SEV_1 = "SEV_1"
    SEV_2 = "SEV_2"
    SEV_3 = "SEV_3"


class PeriodReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class PrecautionTier(str, Enum):
    CLEAR = "CLEAR"
    PRECAUTION = "PRECAUTION"
    CONTRAINDICATION = "CONTRAINDICATION"


class Rider(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    weight_lb: float
    household_income_band: str
    demographic_group: str
    program_code: str
    funding_mode: str
    payer_rate_cents: int
    condition_codes: List[str]
    status: str
    medical_hold_incident_id: Optional[str]
    withdraw_reason: Optional[str]
    independence_level: Optional[str]
    required_sidewalker_count: Optional[int]
    requires_leader: Optional[bool]
    sidewalker_hold_type: Optional[str]
    backriding_required: bool
    assessment_next_due_at: Optional[str]
    assessment_status: str
    active_release_id: Optional[str]
    goals_met_count: int
    created_at: str
    updated_at: str
    version: int


class ConditionPolicy(TypedDict, total=False):
    """PRD 2.4 - a catalogue row exposing only id and created_at."""

    id: str
    condition_code: str
    activity_type: str
    tier: str
    min_instructor_tier: str
    created_at: str


class MedicalRelease(TypedDict, total=False):
    id: str
    rider_id: str
    signed_on: str
    physician_name: str
    cleared_condition_codes: List[str]
    expires_at: str
    revoked_at: Optional[str]
    superseded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    rider_id: str
    assessment_type: str
    performed_on: str
    balance_score: int
    trunk_control_score: int
    rider_weight_lb: float
    backriding_required: bool
    combined_score: int
    independence_level: str
    required_sidewalker_count: int
    requires_leader: bool
    sidewalker_hold_type: str
    next_due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Horse(TypedDict, total=False):
    id: str
    name: str
    body_weight_lb: float
    tack_weight_lb: float
    max_load_lb: float
    status: str
    hold_release_at: Optional[str]
    hold_reason: Optional[str]
    current_week_start_date: str
    current_week_committed_minutes: int
    current_day_committed_minutes: int
    current_day_session_count: int
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    last_retraining_on: str
    age_years: int
    retraining_due_at: str
    suspended_until: Optional[str]
    suspension_reason: Optional[str]
    status: str
    open_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class VolunteerQualification(TypedDict, total=False):
    id: str
    volunteer_id: str
    crew_role: str
    training_hours: float
    signed_off_on: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict, total=False):
    id: str
    full_name: str
    certification_level: str
    certification_expires_at: str
    supervisor_instructor_id: Optional[str]
    ce_hours_accrued: float
    suspended_until: Optional[str]
    certification_status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    rider_id: str
    horse_id: str
    instructor_id: str
    supervising_instructor_id: Optional[str]
    activity_type: str
    scheduled_start: str
    duration_minutes: int
    scheduled_end: str
    mounted_minutes: Optional[int]
    schedule_status: str
    billing_status: str
    cancellation_reason: Optional[str]
    crew_satisfied: bool
    effective_load_lb: float
    precaution_tier: str
    required_instructor_tier: str
    quoted_fee_cents: int
    service_hours: float
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    session_id: str
    volunteer_id: str
    crew_role: str
    hold_type: Optional[str]
    status: str
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Goal(TypedDict, total=False):
    id: str
    rider_id: str
    domain: str
    objective: str
    baseline_rating: int
    target_rating: int
    current_rating: Optional[int]
    consecutive_target_hits: int
    last_rated_at: Optional[str]
    stale_after: str
    status: str
    discontinue_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgressNote(TypedDict, total=False):
    id: str
    session_id: str
    rider_id: str
    author_instructor_id: str
    narrative: str
    goal_ratings: List[Dict[str, Any]]
    status: str
    finalized_at: Optional[str]
    recorded_service_hours: float
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict, total=False):
    id: str
    grant_name: str
    funder_name: str
    awarded_amount_cents: int
    restricted_program_code: Optional[str]
    restricted_demographic: Optional[str]
    period_start: str
    period_end: str
    allocated_amount_cents: int
    remaining_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScholarshipAward(TypedDict, total=False):
    id: str
    rider_id: str
    cap_pct: float
    period_cap_cents: int
    period_start: str
    period_end: str
    period_used_cents: int
    superseded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict, total=False):
    id: str
    session_id: str
    charge_type: str
    amount_cents: int
    allocated_cents: int
    balance_due_cents: int
    scholarship_excluded: bool
    status: str
    reversed_at: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingAllocation(TypedDict, total=False):
    id: str
    charge_id: str
    grant_id: Optional[str]
    scholarship_award_id: Optional[str]
    source_type: str
    sequence_index: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    session_id: str
    implicated_volunteer_id: Optional[str]
    incident_type: str
    injury_reported: bool
    occurred_at: str
    narrative: str
    severity: str
    reported_at: str
    report_due_at: str
    reported_late: bool
    rider_hold_applied: bool
    horse_hold_applied: bool
    volunteer_suspension_applied: bool
    instructor_suspension_applied: bool
    cancelled_session_count: int
    status: str
    reviewer_notes: Optional[str]
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PeriodReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    status: str
    finalized_at: Optional[str]
    total_service_hours: float
    rider_count: int
    veteran_rider_count: int
    volunteer_hours: float
    grant_utilization_cents: int
    scholarship_spend_cents: int
    private_pay_cents: int
    total_charged_cents: int
    amendment_count: int
    amendment_net_cents: int
    created_at: str
    updated_at: str
    version: int
