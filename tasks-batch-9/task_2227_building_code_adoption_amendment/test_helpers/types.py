"""Record shapes and enumerated values declared by the PRD.

Field names are PRD-exact. Per PRD §2.4 most records expose `updated_at` and
`version`; the two append-only families (`PublicComment`, `VoteRecord`) expose
only `id` and `created_at`.
"""
from typing import Any, TypedDict

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
ROLE_COUNCIL_ADMIN = "CouncilAdmin"
ROLE_TECHNICAL_STAFF = "TechnicalStaff"
ROLE_COMMITTEE_MEMBER = "CommitteeMember"
ROLE_COUNCIL_CHAIR = "CouncilChair"
ROLE_JURISDICTION_OFFICIAL = "JurisdictionOfficial"
ROLE_PETITIONER = "Petitioner"

ALL_ROLES = (
    ROLE_COUNCIL_ADMIN,
    ROLE_TECHNICAL_STAFF,
    ROLE_COMMITTEE_MEMBER,
    ROLE_COUNCIL_CHAIR,
    ROLE_JURISDICTION_OFFICIAL,
    ROLE_PETITIONER,
)

# ---------------------------------------------------------------------------
# Enumerated value sets
# ---------------------------------------------------------------------------
CODE_CYCLE_STATUSES = (
    "DRAFT",
    "INTAKE_OPEN",
    "INTAKE_CLOSED",
    "DELIBERATION",
    "RULEMAKING",
    "ADOPTED",
    "ABANDONED",
)
DISCIPLINES = (
    "BUILDING",
    "STRUCTURAL",
    "FIRE_AND_LIFE_SAFETY",
    "ENERGY",
    "MECHANICAL",
    "PLUMBING",
    "ELECTRICAL",
    "ACCESSIBILITY",
)
COMMITTEE_STATUSES = ("FORMING", "SEATED", "DISSOLVED")
SECTORS = (
    "INDUSTRY",
    "FIRE_SERVICE",
    "LOCAL_JURISDICTION",
    "DESIGN_PROFESSIONAL",
    "PUBLIC",
)
REQUIRED_SECTOR_COVERAGE = ("INDUSTRY", "FIRE_SERVICE", "LOCAL_JURISDICTION")
MEMBER_STATUSES = ("ACTIVE", "RECUSED", "RESIGNED")
RECUSAL_ACTIONS = ("RECUSE", "REINSTATE")
STRINGENCY_DIRECTIONS = ("MORE_STRINGENT", "LESS_STRINGENT", "NEUTRAL", "CLARIFYING")
REVIEW_STATUSES = (
    "SUBMITTED",
    "SCREENED",
    "COMMENT_OPEN",
    "COMMENT_CLOSED",
    "APPROVED",
    "REJECTED",
    "RETURNED_FOR_REVISION",
    "WITHDRAWN",
)
ANALYSIS_STATUSES = ("NOT_STARTED", "PENDING", "PARTIAL", "COMPLETE", "STALE")
SCREENING_DECISIONS = ("ACCEPT_FOR_ANALYSIS", "REJECT", "WITHDRAW")
ANALYSIS_TYPES = ("COST_BENEFIT", "ENERGY_IMPACT")
ANALYSIS_ROW_STATUSES = ("SUBMITTED", "ACCEPTED", "RETURNED", "SUPERSEDED")
ANALYSIS_REVIEW_DECISIONS = ("ACCEPT", "RETURN")
COMMENT_WINDOW_ACTIONS = ("OPEN", "EXTEND", "CLOSE")
COMMENT_WINDOW_STATUSES = ("NONE", "OPEN", "CLOSED")
COMMENT_POSITIONS = ("SUPPORT", "OPPOSE", "NEUTRAL")
HEARING_STATUSES = ("SCHEDULED", "CONVENED", "ADJOURNED", "CANCELLED")
AGENDA_MODES = ("AUTO_FILL",)
BALLOTS = ("YES", "NO", "ABSTAIN")
VOTE_OUTCOMES = ("APPROVED", "REJECTED")
VOTE_OUTCOME_REASONS = (
    "MAJORITY_APPROVED",
    "SIMPLE_MAJORITY_FAILED",
    "SUPERMAJORITY_FAILED",
    "FIRE_SERVICE_VETO",
)
ADOPTION_RULE_STATUSES = (
    "DRAFT",
    "FILED",
    "PUBLISHED",
    "EFFECTIVE",
    "WITHDRAWN",
    "SUPERSEDED",
)
LOCAL_AUTHORITY_LEVELS = ("FULL", "LIMITED", "NONE")
ENFORCEMENT_READINESS_VALUES = ("READY", "NOT_READY")
LOCAL_AMENDMENT_STATUSES = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "RETURNED",
    "FILED_EFFECTIVE",
    "REJECTED",
    "VOIDED",
)
LOCAL_REVIEW_DECISIONS = ("START_REVIEW", "ACCEPT", "RETURN", "REJECT")
INTERPRETATION_STATUSES = (
    "SUBMITTED",
    "ASSIGNED",
    "OPINION_DRAFTED",
    "PUBLISHED",
    "DECLINED",
    "SUPERSEDED",
)
INTERPRETATION_ACTIONS = ("ASSIGN", "ISSUE_OPINION", "PUBLISH", "APPEAL", "DECLINE")
BINDING_SCOPES = ("STATEWIDE", "REQUESTING_JURISDICTION_ONLY")
TRAINING_AUDIENCES = ("BUILDING_OFFICIAL", "DESIGN_PROFESSIONAL", "BOTH")
ATTENDEE_ROLES = ("BUILDING_OFFICIAL", "DESIGN_PROFESSIONAL")
TRAINING_SESSION_STATUSES = (
    "SCHEDULED",
    "ENROLLMENT_OPEN",
    "ENROLLMENT_CLOSED",
    "DELIVERED",
    "CANCELLED",
)
ENROLLMENT_STATUSES = ("ENROLLED", "ATTENDED", "NO_SHOW", "CANCELLED")
ATTENDANCE_OUTCOMES = ("ATTENDED", "NO_SHOW")


# ---------------------------------------------------------------------------
# Record shapes
# ---------------------------------------------------------------------------
class CodeCycle(TypedDict):
    id: str
    cycle_year: int
    model_code_edition: str
    intake_opens_at: str
    intake_closes_at: str
    status: str
    seated_committee_count: int
    proposal_count: int
    approved_proposal_count: int
    approved_incremental_cost_cents: int
    approved_permit_backlog_count: int
    created_at: str
    updated_at: str
    version: int


class DisciplineCommittee(TypedDict):
    id: str
    code_cycle_id: str
    discipline: str
    voting_seat_count: int
    active_voting_member_count: int
    quorum_required: int
    sector_coverage_complete: bool
    chair_member_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict):
    id: str
    committee_id: str
    full_name: str
    sector: str
    voting_seat: bool
    is_chair: bool
    status: str
    recusal_reason: Any
    created_at: str
    updated_at: str
    version: int


class AmendmentProposal(TypedDict):
    id: str
    code_cycle_id: str
    committee_id: str
    code_section: str
    discipline: str
    title: str
    proposed_text: str
    stringency_direction: str
    proposer_sector: str
    submitted_by_user_id: str
    review_status: str
    analysis_status: str
    energy_analysis_required: bool
    affected_permit_count: Any
    statewide_incremental_cost_cents: Any
    preliminary_benefit_cost_ratio: Any
    final_benefit_cost_ratio: Any
    support_comment_count: int
    oppose_comment_count: int
    total_comment_count: int
    comment_window_status: str
    comment_opens_at: Any
    comment_closes_at: Any
    comment_extension_count: int
    comment_round: int
    revision_round: int
    base_docket_score: Any
    docket_queue_rank: Any
    docket_priority_score: Any
    created_at: str
    updated_at: str
    version: int


class ImpactAnalysis(TypedDict):
    id: str
    proposal_id: str
    analysis_type: str
    prepared_by_user_id: str
    reviewed_by_user_id: Any
    incremental_cost_by_occupancy: Any
    affected_permit_count: Any
    annual_cost_savings_cents: Any
    measure_life_years: Any
    annual_energy_savings_kwh: Any
    energy_delta_pct: Any
    statewide_incremental_cost_cents: Any
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only per PRD §2.4: only id and created_at; no updated_at, no version.
class PublicComment(TypedDict):
    id: str
    proposal_id: str
    commenter_sector: str
    position: str
    body: str
    submitted_by_user_id: str
    comment_round: int
    received_at: str
    created_at: str


class Hearing(TypedDict):
    id: str
    committee_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    agenda_proposal_ids: list
    present_member_ids: Any
    present_voting_count: Any
    quorum_required_at_convene: Any
    convened_at: Any
    adjourned_at: Any
    created_at: str
    updated_at: str
    version: int


# Append-only per PRD §2.4: only id and created_at; no updated_at, no version.
class VoteRecord(TypedDict):
    id: str
    hearing_id: str
    proposal_id: str
    ballots: list
    voting_seats_at_call: int
    quorum_required: int
    yes_count: int
    no_count: int
    abstain_count: int
    absent_count: int
    outcome: str
    outcome_reason: str
    final_benefit_cost_ratio_at_vote: Any
    recorded_by_user_id: str
    created_at: str


class AdoptionRule(TypedDict):
    id: str
    code_cycle_id: str
    title: str
    base_date: Any
    projected_permit_backlog: Any
    transition_grace_days: Any
    notice_days: Any
    effective_date: Any
    transition_cutoff_date: Any
    prior_code_expiry_date: Any
    approved_incremental_cost_cents_at_filing: Any
    pinned_amendment_versions: Any
    status: str
    filed_by_user_id: Any
    published_by_user_id: Any
    published_at: Any
    statewide_readiness_pct_at_effective: Any
    withdrawal_reason: Any
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict):
    id: str
    name: str
    population: int
    local_authority_level: str
    host_seat_capacity: int
    official_headcount: int
    compliance_pct_enrollment_basis: float
    compliance_pct_attendance_basis: float
    enforcement_readiness: str
    effective_local_amendment_count: int
    created_at: str
    updated_at: str
    version: int


class LocalAmendment(TypedDict):
    id: str
    jurisdiction_id: str
    adoption_rule_id: str
    code_section: str
    local_text: str
    stringency_direction: str
    justification: str
    filed_within_window: bool
    revision_round: int
    reviewed_by_user_id: Any
    status: str
    created_at: str
    updated_at: str
    version: int


class InterpretationRequest(TypedDict):
    id: str
    adoption_rule_id: str
    jurisdiction_id: Any
    supersedes_request_id: Any
    assigned_committee_id: Any
    code_section: str
    question: str
    requested_by_user_id: str
    opinion_text: Any
    binding_scope: Any
    opinion_number: Any
    drafted_by_user_id: Any
    published_by_user_id: Any
    published_at: Any
    appeal_round: int
    decline_reason: Any
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict):
    id: str
    adoption_rule_id: str
    host_jurisdiction_id: str
    discipline: str
    audience: str
    seat_capacity: int
    starts_at: str
    ends_at: str
    seats_available: int
    enrolled_count: int
    attended_count: int
    no_show_count: int
    cancellation_reason: Any
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict):
    id: str
    training_session_id: str
    jurisdiction_id: str
    attendee_name: str
    attendee_role: str
    enrolled_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
