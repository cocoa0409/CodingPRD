"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    COMMITTEE_MEMBER = "CommitteeMember"
    VOLUNTEER = "Volunteer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRAINING_COORDINATOR = "TrainingCoordinator"
    DEVELOPMENT_COORDINATOR = "DevelopmentCoordinator"


# --------------------------------------------------------------------------
# Enumerated domains
# --------------------------------------------------------------------------
class VolunteerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    IN_TRAINING = "IN_TRAINING"
    CERTIFIED = "CERTIFIED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    RESIGNED = "RESIGNED"


class RoleTrack(str, Enum):
    PROGRAMMER = "PROGRAMMER"
    ENGINEER = "ENGINEER"
    DEVELOPMENT = "DEVELOPMENT"


class CertificationStatus(str, Enum):
    PENDING_EXAM = "PENDING_EXAM"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CertType(str, Enum):
    BOARD_OPERATION = "BOARD_OPERATION"
    STATION_POLICY = "STATION_POLICY"
    BROADCAST_REGULATION = "BROADCAST_REGULATION"
    UNDERWRITING_COPY = "UNDERWRITING_COPY"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_COMMITTEE = "IN_COMMITTEE"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class FormatCode(str, Enum):
    MUSIC = "MUSIC"
    PUBLIC_AFFAIRS = "PUBLIC_AFFAIRS"
    TALK = "TALK"
    NEWS = "NEWS"
    CULTURAL = "CULTURAL"


class Daypart(str, Enum):
    MORNING_DRIVE = "MORNING_DRIVE"
    MIDDAY = "MIDDAY"
    AFTERNOON_DRIVE = "AFTERNOON_DRIVE"
    EVENING = "EVENING"
    OVERNIGHT = "OVERNIGHT"


class Recommendation(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    DECLINE = "DECLINE"


class ProgrammingStatus(str, Enum):
    APPROVED_UNSCHEDULED = "APPROVED_UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    ON_AIR_ACTIVE = "ON_AIR_ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    PROBATION = "PROBATION"
    CANCELLED = "CANCELLED"


class ComplianceStanding(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"


class ReviewWindow(str, Enum):
    TRAILING_SIX = "TRAILING_SIX"
    QUARTER_TO_DATE = "QUARTER_TO_DATE"


class GridStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class SlotStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    PREEMPTED = "PREEMPTED"


class ConflictPolicy(str, Enum):
    REJECT = "REJECT"
    SENIORITY_PREEMPT = "SENIORITY_PREEMPT"


class AirStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AIRED = "AIRED"
    SUBSTITUTE_AIRED = "SUBSTITUTE_AIRED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class LogStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    DELINQUENT = "DELINQUENT"


class PlaySource(str, Enum):
    LIBRARY_CD = "LIBRARY_CD"
    LIBRARY_VINYL = "LIBRARY_VINYL"
    DIGITAL = "DIGITAL"
    LIVE_PERFORMANCE = "LIVE_PERFORMANCE"
    PRODUCTION_MUSIC = "PRODUCTION_MUSIC"


class RoyaltyClass(str, Enum):
    FEATURED = "FEATURED"
    INCIDENTAL = "INCIDENTAL"
    EXEMPT = "EXEMPT"


class SpotClass(str, Enum):
    UNDERWRITING = "UNDERWRITING"
    POLITICAL_CANDIDATE = "POLITICAL_CANDIDATE"
    ISSUE_ADVOCACY = "ISSUE_ADVOCACY"
    PSA = "PSA"


class SpotStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    APPROVED_WITH_EDITS = "APPROVED_WITH_EDITS"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class PublicFileStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    POSTED = "POSTED"
    LATE_POSTED = "LATE_POSTED"
    MISSING = "MISSING"


class ComplianceFlag(str, Enum):
    CALL_TO_ACTION = "CALL_TO_ACTION"
    PRICE_INFO = "PRICE_INFO"
    COMPARATIVE_CLAIM = "COMPARATIVE_CLAIM"
    MISSING_SPONSOR_ID = "MISSING_SPONSOR_ID"


class IncidentCategory(str, Enum):
    INDECENCY = "INDECENCY"
    POLITICAL_CONTENT = "POLITICAL_CONTENT"
    PUBLIC_FILE = "PUBLIC_FILE"
    SPONSOR_ID = "SPONSOR_ID"
    VOLUNTEER_CONFLICT = "VOLUNTEER_CONFLICT"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNFOUNDED = "UNFOUNDED"
    REMEDIATED = "REMEDIATED"


class Sanction(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    SUSPENSION = "SUSPENSION"
    TERMINATION = "TERMINATION"


class DriveStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class PremiumStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    LAPSED = "LAPSED"
    REFUNDED = "REFUNDED"


class PledgePremiumStatus(str, Enum):
    RESERVED = "RESERVED"
    BACKORDERED = "BACKORDERED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    WAIVED = "WAIVED"
    SHIPPED = "SHIPPED"
    RELEASED = "RELEASED"
    RETURNED = "RETURNED"


# --------------------------------------------------------------------------
# Entity shapes
#
# Records that carry the standard server-managed properties of PRD §2.5 list
# id, created_at, updated_at and version. The two write-once evidence records
# — the committee ballot and one logged spin — carry only id and created_at.
# --------------------------------------------------------------------------
class Volunteer(TypedDict):
    id: str
    legal_name: str
    email: str
    role_track: str
    seniority_start_date: str
    committee_seat: bool
    status: str
    continuous_service_months: int
    current_certification_count: int
    strike_count: int
    seniority_score: float
    needs_core_renewal: bool
    created_at: str
    updated_at: str
    version: int


class CertificationRecord(TypedDict):
    id: str
    volunteer_id: str
    cert_type: str
    status: str
    exam_score: Optional[int]
    attempt_count: int
    issued_on: Optional[str]
    expires_on: Optional[str]
    last_attempt_at: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramProposal(TypedDict):
    id: str
    proposer_volunteer_id: str
    title: str
    format_code: str
    language_code: str
    requested_daypart: str
    requested_duration_minutes: int
    diversity_tags: List[str]
    status: str
    review_round: int
    composite_score: Optional[float]
    decline_majority: bool
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeVote(TypedDict):
    """Write-once committee ballot — no updated_at and no version (PRD §2.5)."""

    id: str
    proposal_id: str
    member_volunteer_id: str
    review_round: int
    format_fit_score: int
    diversity_score: int
    quality_score: int
    recommendation: str
    rationale: Optional[str]
    created_at: str


class Program(TypedDict):
    id: str
    proposal_id: str
    host_volunteer_id: str
    title: str
    format_code: str
    programming_status: str
    compliance_standing: str
    compliance_penalty_points: int
    performance_score: Optional[float]
    performance_score_method: Optional[str]
    last_evaluated_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScheduleGrid(TypedDict):
    id: str
    season_code: str
    effective_from: str
    effective_to: str
    status: str
    total_assigned_minutes: int
    public_affairs_minutes_pct: float
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SlotAssignment(TypedDict):
    id: str
    grid_id: str
    program_id: str
    day_of_week: int
    start_minute: int
    duration_minutes: int
    status: str
    preempted_by_program_id: Optional[str]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Episode(TypedDict):
    id: str
    program_id: str
    slot_assignment_id: str
    board_operator_volunteer_id: Optional[str]
    scheduled_start_utc: str
    air_status: str
    log_status: str
    needs_substitute: bool
    featured_performance_count: int
    local_featured_count: int
    provisional_royalty_cents: Optional[int]
    final_royalty_cents: Optional[int]
    log_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlaylistEntry(TypedDict):
    """Write-once logged spin — no updated_at and no version (PRD §2.5)."""

    id: str
    episode_id: str
    sequence_number: int
    artist: str
    title: str
    album: Optional[str]
    label: Optional[str]
    duration_seconds: int
    play_source: str
    is_local_artist: bool
    is_new_release: bool
    royalty_class: str
    created_at: str


class UnderwritingSpot(TypedDict):
    id: str
    underwriter_name: str
    spot_class: str
    copy_text: str
    assigned_program_id: Optional[str]
    flight_start: str
    flight_end: str
    status: str
    noncommercial_risk_score: int
    compliance_flags: Optional[List[str]]
    approved_copy_text: Optional[str]
    reviewed_by_user_id: Optional[str]
    public_file_status: str
    public_file_due_at: Optional[str]
    public_file_posted_at: Optional[str]
    public_file_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceIncident(TypedDict):
    id: str
    category: str
    severity: str
    occurred_at: str
    complainant_note: str
    program_id: Optional[str]
    episode_id: Optional[str]
    underwriting_spot_id: Optional[str]
    respondent_volunteer_id: Optional[str]
    sanction: str
    status: str
    penalty_points: int
    safe_harbor_violation: bool
    adjudicated_by_user_id: Optional[str]
    remediation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MembershipDrive(TypedDict):
    id: str
    name: str
    goal_cents: int
    start_at: str
    end_at: str
    phone_line_count: int
    status: str
    gross_pledged_cents: int
    pledged_total_cents: int
    fulfilled_total_cents: int
    refunded_total_cents: int
    lapsed_total_cents: int
    attainment_pct: float
    created_at: str
    updated_at: str
    version: int


class PhoneBankShift(TypedDict):
    id: str
    drive_id: str
    volunteer_id: str
    start_at: str
    end_at: str
    status: str
    pledges_taken_count: int
    created_at: str
    updated_at: str
    version: int


class PremiumItem(TypedDict):
    id: str
    sku: str
    name: str
    tier_threshold_cents: int
    fair_market_value_cents: int
    units_received_qty: int
    on_hand_qty: int
    reserved_qty: int
    shipped_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Pledge(TypedDict):
    id: str
    drive_id: str
    donor_name: str
    amount_cents: int
    shift_id: Optional[str]
    premium_item_id: Optional[str]
    payment_status: str
    premium_status: str
    tax_deductible_cents: int
    created_at: str
    updated_at: str
    version: int
