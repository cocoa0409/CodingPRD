"""Domain types for the Pro Bono Matching API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    SCOPING_SPECIALIST = "ScopingSpecialist"
    VOLUNTEER = "Volunteer"
    PARTNER_CONTACT = "PartnerContact"
    QUALITY_REVIEWER = "QualityReviewer"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class PartnerOrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class ProbationReason(str, Enum):
    LOW_SATISFACTION = "LOW_SATISFACTION"
    SCOPE_CREEP_ABUSE = "SCOPE_CREEP_ABUSE"
    MANUAL = "MANUAL"


class CapacityClass(str, Enum):
    MICRO = "MICRO"
    SMALL = "SMALL"
    MID = "MID"
    LARGE = "LARGE"


class Sector(str, Enum):
    HEALTH = "HEALTH"
    EDUCATION = "EDUCATION"
    HOUSING = "HOUSING"
    ENVIRONMENT = "ENVIRONMENT"
    ARTS = "ARTS"
    CIVIC = "CIVIC"


class CyclePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ProjectRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SCOPING = "SCOPING"
    SCOPED = "SCOPED"
    MATCHING = "MATCHING"
    RESCOPING = "RESCOPING"
    ENGAGED = "ENGAGED"
    IN_DELIVERY = "IN_DELIVERY"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class Discipline(str, Enum):
    LEGAL = "LEGAL"
    ACCOUNTING = "ACCOUNTING"
    TECHNOLOGY = "TECHNOLOGY"
    MARKETING = "MARKETING"
    HR = "HR"
    STRATEGY = "STRATEGY"


class Urgency(str, Enum):
    ROUTINE = "ROUTINE"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class ScopeDefinitionStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ConfidentialityTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    RESTRICTED = "RESTRICTED"


class IpDisposition(str, Enum):
    ASSIGN_TO_PARTNER = "ASSIGN_TO_PARTNER"
    LICENSE_PERPETUAL = "LICENSE_PERPETUAL"
    RETAINED_BY_VOLUNTEER = "RETAINED_BY_VOLUNTEER"


class DeliverableReviewStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WAIVED = "WAIVED"


class WaivedReason(str, Enum):
    DESCOPED_BY_CHANGE = "DESCOPED_BY_CHANGE"
    PARTNER_WITHDRAWN = "PARTNER_WITHDRAWN"


class VolunteerStatus(str, Enum):
    PENDING_VETTING = "PENDING_VETTING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DEACTIVATED = "DEACTIVATED"


class PauseReason(str, Enum):
    RELIABILITY_FLOOR = "RELIABILITY_FLOOR"
    SELF_REQUESTED = "SELF_REQUESTED"
    ADMIN = "ADMIN"


class Seniority(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    SENIOR = "SENIOR"
    PRINCIPAL = "PRINCIPAL"
    PARTNER = "PARTNER"


class WindowKind(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class AvailabilityWindowStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class MatchOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class DeclineReason(str, Enum):
    SCOPE_TOO_LARGE = "SCOPE_TOO_LARGE"
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"
    OUTSIDE_EXPERTISE = "OUTSIDE_EXPERTISE"
    IP_TERMS_UNACCEPTABLE = "IP_TERMS_UNACCEPTABLE"


class WithdrawReason(str, Enum):
    CYCLE_FROZEN = "CYCLE_FROZEN"
    RESCOPED = "RESCOPED"
    PARTNER_SUSPENDED = "PARTNER_SUSPENDED"
    VOLUNTEER_PAUSED = "VOLUNTEER_PAUSED"
    ADMIN = "ADMIN"


class WorkStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    HANDED_OFF = "HANDED_OFF"
    TERMINATED = "TERMINATED"


class ValuationStatus(str, Enum):
    UNVALUED = "UNVALUED"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    RESTATED = "RESTATED"


class QualityGate(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"


class CreepEscalationLevel(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    ESCALATED = "ESCALATED"
    BREACH = "BREACH"


class TerminationReason(str, Enum):
    QUALITY_FAILURE = "QUALITY_FAILURE"
    SCOPE_BREACH = "SCOPE_BREACH"
    AGREEMENT_VOIDED = "AGREEMENT_VOIDED"
    PARTNER_SUSPENDED = "PARTNER_SUSPENDED"
    ADMIN = "ADMIN"


class AgreementStatus(str, Enum):
    DRAFTED = "DRAFTED"
    SENT = "SENT"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class VoidReason(str, Enum):
    COUNTER_LIMIT_EXCEEDED = "COUNTER_LIMIT_EXCEEDED"
    TERMS_REJECTED = "TERMS_REJECTED"
    ENGAGEMENT_TERMINATED = "ENGAGEMENT_TERMINATED"


class CounteringParty(str, Enum):
    VOLUNTEER = "VOLUNTEER"
    PARTNER = "PARTNER"


class CheckinStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    MISSED = "MISSED"
    WAIVED = "WAIVED"


class MilestoneWaiverReason(str, Enum):
    RESCOPED = "RESCOPED"
    ENGAGEMENT_TERMINATED = "ENGAGEMENT_TERMINATED"
    ADMIN = "ADMIN"


class ActivityClass(str, Enum):
    DELIVERY = "DELIVERY"
    ADMIN = "ADMIN"
    TRAVEL = "TRAVEL"


class ScopeChangeStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    VOIDED = "VOIDED"


class DecisionTier(str, Enum):
    AUTO_APPROVABLE = "AUTO_APPROVABLE"
    MANAGER_REVIEW = "MANAGER_REVIEW"
    RESCOPE_REQUIRED = "RESCOPE_REQUIRED"


class QualityReviewStatus(str, Enum):
    OPEN = "OPEN"
    SCORED = "SCORED"
    DECIDED = "DECIDED"
    REWORK_REQUESTED = "REWORK_REQUESTED"


class ReviewOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class ValuationMethod(str, Enum):
    MARKET_RATE = "MARKET_RATE"
    INDEPENDENT_SECTOR = "INDEPENDENT_SECTOR"


class VariantLabel(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    RESTATED = "RESTATED"


# --------------------------------------------------------------------------
# Entities carrying the full audit set (id, created_at, updated_at, version)
# --------------------------------------------------------------------------
class PartnerOrg(TypedDict):
    id: str
    name: str
    contact_email: str
    sector: str
    annual_budget_usd: float
    capacity_class: str
    max_concurrent_engagements: int
    open_engagement_count: int
    satisfaction_index: Optional[float]
    satisfaction_sample_size: int
    status: str
    probation_reason: Optional[str]
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramCycle(TypedDict):
    id: str
    cycle_code: str
    starts_at: str
    ends_at: str
    capacity_slot_total: int
    slots_committed: int
    slots_reserved: int
    slots_available: int
    utilization_ratio: float
    posture: str
    last_recalculated_at: Optional[str]
    recalc_epoch: int
    created_at: str
    updated_at: str
    version: int


class ProjectRequest(TypedDict):
    id: str
    partner_org_id: str
    cycle_id: str
    title: str
    discipline: str
    required_skill_code: str
    min_proficiency: int
    requested_hours: float
    urgency: str
    status: str
    active_scope_revision_no: int
    rescope_count: int
    failed_match_rounds: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScopeDefinition(TypedDict):
    id: str
    project_request_id: str
    supersedes_scope_id: Optional[str]
    revision_no: int
    authored_by_user_id: str
    estimated_hours: float
    complexity_factor: float
    confidentiality_tier: str
    ip_disposition: str
    deliverable_weight_total_pct: float
    deliverable_count: int
    status: str
    approved_at: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    full_name: str
    email: str
    professional_rate_usd_per_hour: float
    seniority: str
    weekly_hours_cap: int
    credential_verified_at: Optional[str]
    reliability_score: float
    reliability_score_lifetime: float
    terminal_engagement_count: int
    open_engagement_count: int
    lifetime_valued_usd: float
    status: str
    pause_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchOffer(TypedDict):
    id: str
    project_request_id: str
    volunteer_id: str
    scope_definition_id: str
    availability_window_id: str
    round_no: int
    match_score: float
    reserved_hours: float
    offered_at: str
    expires_at: str
    status: str
    decline_reason: Optional[str]
    withdraw_reason: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    match_offer_id: str
    project_request_id: str
    volunteer_id: str
    scope_definition_id: str
    cycle_id: str
    availability_window_id: str
    committed_hours: float
    approved_hours: float
    scope_creep_pct: float
    creep_escalation_level: str
    work_status: str
    valuation_status: str
    quality_gate: str
    confidentiality_attested: bool
    handoff_artifact_count: int
    missed_checkin_count: int
    handoff_at: Optional[str]
    terminated_at: Optional[str]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EngagementAgreement(TypedDict):
    id: str
    engagement_id: str
    ip_disposition: str
    confidentiality_tier: str
    indemnity_cap_usd: float
    counter_round: int
    terms_revision_no: int
    last_countered_by: Optional[str]
    volunteer_signed_at: Optional[str]
    partner_signed_at: Optional[str]
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    engagement_id: str
    sequence_no: int
    due_at: str
    checkin_status: str
    held_at: Optional[str]
    reported_cumulative_hours: Optional[float]
    variance_hours: Optional[float]
    escalation_raised: bool
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScopeChangeRequest(TypedDict):
    id: str
    engagement_id: str
    requested_by: str
    additional_hours: float
    additional_deliverable_count: int
    justification: str
    projected_creep_pct: float
    decision_tier: str
    status: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    resulting_scope_revision_no: Optional[int]
    created_at: str
    updated_at: str
    version: int


class QualityReview(TypedDict):
    id: str
    engagement_id: str
    reviewer_user_id: str
    round_no: int
    scored_deliverable_count: int
    weighted_score: Optional[float]
    outcome: str
    status: str
    rework_deadline_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ValuationRecord(TypedDict):
    id: str
    engagement_id: str
    method: str
    sequence_no: int
    hours_included: float
    rate_applied_usd: float
    base_amount_usd: float
    admin_overhead_usd: float
    total_amount_usd: float
    variant_label: str
    superseded_at: Optional[str]
    posted_at: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Lighter resource kinds: only id + created_at (PRD §2.4) — no updated_at,
# no version.
# --------------------------------------------------------------------------
class Deliverable(TypedDict):
    id: str
    scope_definition_id: str
    title: str
    sequence_no: int
    weight_pct: float
    hours_estimate: float
    acceptance_criteria: str
    review_status: str
    review_score: Optional[int]
    waived_reason: Optional[str]
    created_at: str


class SkillProfile(TypedDict):
    id: str
    volunteer_id: str
    skill_code: str
    proficiency: int
    years_experience: float
    verified: bool
    verified_at: Optional[str]
    created_at: str


class AvailabilityWindow(TypedDict):
    id: str
    volunteer_id: str
    starts_at: str
    ends_at: str
    window_kind: str
    hours_offered: float
    hours_committed: float
    hours_remaining: float
    status: str
    created_at: str


class TimeLog(TypedDict):
    id: str
    engagement_id: str
    milestone_id: Optional[str]
    work_date: str
    hours: float
    activity_class: str
    rate_basis_usd: float
    approved: bool
    approved_at: Optional[str]
    logged_by_user_id: str
    created_at: str


class SatisfactionSurvey(TypedDict):
    id: str
    engagement_id: str
    partner_org_id: str
    submitted_at: str
    score_expertise: int
    score_responsiveness: int
    score_deliverable_fit: int
    would_recommend: bool
    composite_score: float
    counted_in_index: bool
    created_at: str


LIGHT_ENTITY_NAMES = [
    "Deliverable", "SkillProfile", "AvailabilityWindow", "TimeLog",
    "SatisfactionSurvey",
]
