"""Domain types for the Grief & Bereavement Support API.

Entity TypedDicts, status enums and the role enum, derived from the PRD.
Resources that carry `updated_at` and `version` are distinguished from the one
immutable clinical record (an assessment) that carries only `id` and `created_at`.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum (PRD 2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    REFERRAL_SOURCE = "ReferralSource"
    COUNSELOR = "Counselor"
    VOLUNTEER_COMPANION = "VolunteerCompanion"
    PARTICIPANT = "Participant"
    GRANT_OFFICER = "GrantOfficer"


# --------------------------------------------------------------------------
# Shared clinical vocabularies
# --------------------------------------------------------------------------
class LossType(str, Enum):
    ANTICIPATED_ILLNESS = "ANTICIPATED_ILLNESS"
    SUDDEN_DEATH = "SUDDEN_DEATH"
    PERINATAL = "PERINATAL"
    SUICIDE = "SUICIDE"
    OVERDOSE = "OVERDOSE"
    PEDIATRIC = "PEDIATRIC"


class RelationshipToDeceased(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"
    SIBLING = "SIBLING"
    OTHER_FAMILY = "OTHER_FAMILY"
    FRIEND = "FRIEND"
    CAREGIVER = "CAREGIVER"


class SourceType(str, Enum):
    HOSPICE = "HOSPICE"
    FUNERAL_HOME = "FUNERAL_HOME"
    SELF = "SELF"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCREENED = "SCREENED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class ScreeningBand(str, Enum):
    URGENT = "URGENT"
    PRIORITY = "PRIORITY"
    ROUTINE = "ROUTINE"


class DeclineReason(str, Enum):
    OUT_OF_AREA = "OUT_OF_AREA"
    DUPLICATE = "DUPLICATE"
    DECLINED_SERVICES = "DECLINED_SERVICES"
    INELIGIBLE_TIMING = "INELIGIBLE_TIMING"


class ServiceStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSESSED = "ASSESSED"
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    DISCHARGED = "DISCHARGED"
    WITHDRAWN = "WITHDRAWN"


class OutreachStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_HOLD = "ON_HOLD"
    LAPSED = "LAPSED"
    CLOSED = "CLOSED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class AssessmentKind(str, Enum):
    NEEDS = "NEEDS"
    BASELINE = "BASELINE"
    MIDPOINT = "MIDPOINT"
    EXIT = "EXIT"


class Instrument(str, Enum):
    ICG_SF = "ICG_SF"
    PG13 = "PG13"


class MeetingSpaceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class CohortStatus(str, Enum):
    FORMING = "FORMING"
    OPEN_ENROLLMENT = "OPEN_ENROLLMENT"
    UNDERSUBSCRIBED = "UNDERSUBSCRIBED"
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    ATTENDING = "ATTENDING"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class WithdrawReason(str, Enum):
    PARTICIPANT_REQUEST = "PARTICIPANT_REQUEST"
    NO_SHOW = "NO_SHOW"
    TRANSFERRED = "TRANSFERRED"
    PROGRAM_CANCELLED = "PROGRAM_CANCELLED"


class LicenseType(str, Enum):
    LCSW = "LCSW"
    LPC = "LPC"
    PSYCHOLOGIST = "PSYCHOLOGIST"
    CHAPLAIN = "CHAPLAIN"


class CounselorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CounselingReferralStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    ASSIGNED = "ASSIGNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Urgency(str, Enum):
    ROUTINE = "ROUTINE"
    PRIORITY = "PRIORITY"
    URGENT = "URGENT"


class CloseReason(str, Enum):
    COMPLETED = "COMPLETED"
    PARTICIPANT_WITHDRAWN = "PARTICIPANT_WITHDRAWN"
    COUNSELOR_UNAVAILABLE = "COUNSELOR_UNAVAILABLE"
    DECLINED = "DECLINED"


class VolunteerCompanionStatus(str, Enum):
    APPLIED = "APPLIED"
    IN_TRAINING = "IN_TRAINING"
    CERTIFIED = "CERTIFIED"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"


class CompanionMatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    ENDED = "ENDED"


class MatchEndReason(str, Enum):
    COMPLETED = "COMPLETED"
    COMPANION_LAPSED = "COMPANION_LAPSED"
    PARTICIPANT_WITHDRAWN = "PARTICIPANT_WITHDRAWN"
    MISMATCH = "MISMATCH"


class RemembranceEventStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class InvitationStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class GrantAwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AllocationCategory(str, Enum):
    GROUP_PROGRAM = "GROUP_PROGRAM"
    REMEMBRANCE_EVENT = "REMEMBRANCE_EVENT"
    COUNSELING = "COUNSELING"
    VOLUNTEER_TRAINING = "VOLUNTEER_TRAINING"


class AllocationBasis(str, Enum):
    PROJECTED_ENROLLMENT = "PROJECTED_ENROLLMENT"
    EVENT_PLAN = "EVENT_PLAN"
    ACTUAL_ATTENDANCE = "ACTUAL_ATTENDANCE"
    CONFIRMED_HEADCOUNT = "CONFIRMED_HEADCOUNT"


class FundingAllocationStatus(str, Enum):
    COMMITTED = "COMMITTED"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"


class GrantReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class OutreachOccasion(str, Enum):
    ONE_MONTH = "ONE_MONTH"
    THREE_MONTH = "THREE_MONTH"
    SIX_MONTH = "SIX_MONTH"
    FIRST_ANNIVERSARY = "FIRST_ANNIVERSARY"


class OutreachTouchpointStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    NO_RESPONSE = "NO_RESPONSE"
    CANCELLED = "CANCELLED"


class OutreachChannel(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Referral(TypedDict):
    id: str
    source_type: str
    source_org_name: Optional[str]
    decedent_name: str
    date_of_death: str
    relationship_to_deceased: str
    loss_type: str
    contact_name: str
    contact_email: str
    status: str
    screening_band: Optional[str]
    days_since_death: Optional[int]
    eligibility_note: Optional[str]
    decline_reason: Optional[str]
    participant_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    referral_id: str
    display_name: str
    loss_type: str
    relationship_to_deceased: str
    date_of_death: str
    anniversary_month_day: str
    service_status: str
    outreach_status: str
    risk_tier: str
    composite_need_index: float
    waitlist_reentry_count: int
    sessions_attended_total: int
    outreach_cadence_days: int
    baseline_score: Optional[float]
    latest_score: Optional[float]
    has_active_companion: bool
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    """An assessment is an immutable clinical observation: id and created_at only."""

    id: str
    participant_id: str
    kind: str
    instrument: str
    grief_severity: int
    isolation_index: int
    functional_impairment: int
    suicidality_flag: bool
    raw_total: int
    normalized_score: float
    recorded_at: str
    sequence_index: int
    created_at: str


class MeetingSpace(TypedDict):
    id: str
    name: str
    capacity: int
    turnover_buffer_minutes: int
    accessibility_features: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict):
    id: str
    name: str
    loss_type: str
    meeting_space_id: str
    seats_total: int
    min_viable_enrollment: int
    seats_held: int
    seats_filled: int
    seats_open: int
    weekday: str
    start_minute_utc: int
    duration_minutes: int
    series_start_date: str
    sessions_total: int
    series_end_date: str
    status: str
    direct_cost_cents: int
    admin_fee_cents: int
    program_cost_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    participant_id: str
    cohort_id: str
    status: str
    held_until: str
    sessions_attended: int
    attendance_ratio: float
    withdraw_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Counselor(TypedDict):
    id: str
    full_name: str
    license_type: str
    specialties: List[str]
    caseload_cap: int
    weekly_capacity_minutes: int
    active_caseload: int
    committed_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CounselingReferral(TypedDict):
    id: str
    participant_id: str
    counselor_id: Optional[str]
    requested_minutes_per_week: int
    urgency: str
    required_specialty: str
    status: str
    queue_priority: float
    waitlisted_at: str
    assigned_at: Optional[str]
    close_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VolunteerCompanion(TypedDict):
    id: str
    full_name: str
    endorsed_loss_types: List[str]
    max_concurrent_matches: int
    training_hours: float
    modules_completed: List[str]
    certified_on: Optional[str]
    certification_expires_on: Optional[str]
    active_match_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CompanionMatch(TypedDict):
    id: str
    companion_id: str
    participant_id: str
    status: str
    match_score: float
    started_on: Optional[str]
    ended_on: Optional[str]
    end_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemembranceEvent(TypedDict):
    id: str
    title: str
    meeting_space_id: str
    event_date: str
    start_minute_utc: int
    duration_minutes: int
    expected_attendance: int
    status: str
    invitations_sent: int
    invitations_accepted: int
    confirmed_headcount: int
    direct_cost_cents: int
    admin_fee_cents: int
    program_cost_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Invitation(TypedDict):
    id: str
    event_id: str
    participant_id: str
    guest_count: int
    status: str
    rsvp_deadline: str
    sent_at: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantAward(TypedDict):
    id: str
    funder_name: str
    award_reference: str
    awarded_cents: int
    committed_cents: int
    spent_cents: int
    available_cents: int
    allowed_categories: List[str]
    period_start: str
    period_end: str
    indirect_rate_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingAllocation(TypedDict):
    id: str
    grant_award_id: str
    cohort_id: Optional[str]
    event_id: Optional[str]
    category: str
    provisional_cents: int
    settled_cents: Optional[int]
    basis: str
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantReport(TypedDict):
    id: str
    grant_award_id: str
    period_start: str
    period_end: str
    status: str
    line_count: int
    direct_total_cents: int
    indirect_total_cents: int
    reported_total_cents: int
    participants_served: int
    submitted_by_user_id: Optional[str]
    submitted_at: Optional[str]
    return_reason: Optional[str]
    revision_index: int
    created_at: str
    updated_at: str
    version: int


class AnniversaryOutreach(TypedDict):
    id: str
    participant_id: str
    occasion: str
    due_on: str
    status: str
    channel: str
    escalated: bool
    sent_at: Optional[str]
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutcomeSummary(TypedDict):
    participant_id: str
    baseline_score: Optional[float]
    latest_score: Optional[float]
    raw_delta: Optional[float]
    rtm_correction: Optional[float]
    attendance_ratio_capped: float
    attendance_adjusted_delta: Optional[float]
    sessions_attended_total: int
