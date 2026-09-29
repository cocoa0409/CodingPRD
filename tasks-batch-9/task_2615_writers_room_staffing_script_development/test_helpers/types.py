"""Typed shapes for the writers-room staffing and script development API.

One TypedDict per entity, mirroring the contract's field names exactly. Thirteen
entities carry the common quartet id / created_at / updated_at / version; the
append-only fee ledger row carries only id and created_at.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --- Roles -------------------------------------------------------------------

class UserRole(str, Enum):
    STUDIO_EXECUTIVE = "StudioExecutive"
    SHOWRUNNER = "Showrunner"
    WRITER = "Writer"
    GUILD_ADMINISTRATOR = "GuildAdministrator"
    LEGAL_COUNSEL = "LegalCounsel"


# --- Enumerations ------------------------------------------------------------

class WriterLevel(str, Enum):
    STAFF_WRITER = "STAFF_WRITER"
    STORY_EDITOR = "STORY_EDITOR"
    EXEC_STORY_EDITOR = "EXEC_STORY_EDITOR"
    CO_PRODUCER = "CO_PRODUCER"
    PRODUCER = "PRODUCER"


class LengthFormat(str, Enum):
    HALF_HOUR = "HALF_HOUR"
    ONE_HOUR = "ONE_HOUR"


class CommitmentType(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    CONSUMED = "CONSUMED"


class GuaranteeApplicationMode(str, Enum):
    FORWARD_COMMIT = "FORWARD_COMMIT"
    CHRONOLOGICAL_ON_ACCEPTANCE = "CHRONOLOGICAL_ON_ACCEPTANCE"


class CoveragePosture(str, Enum):
    COVERED = "COVERED"
    AT_RISK = "AT_RISK"
    CRITICAL = "CRITICAL"


class RoomFormat(str, Enum):
    IN_PERSON = "IN_PERSON"
    REMOTE = "REMOTE"
    MINI_ROOM = "MINI_ROOM"


class RoomStatus(str, Enum):
    OPEN = "OPEN"
    STAFFING = "STAFFING"
    ACTIVE = "ACTIVE"
    WRAPPED = "WRAPPED"


class FacilityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class SeatStatus(str, Enum):
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    RELEASED = "RELEASED"


class ProductionUnit(str, Enum):
    UNIT_A = "UNIT_A"
    UNIT_B = "UNIT_B"


class ScriptReadiness(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    LOCKED = "LOCKED"


class CreditStatus(str, Enum):
    PENDING = "PENDING"
    SUBMISSIONS_OPEN = "SUBMISSIONS_OPEN"
    SUBMISSIONS_CLOSED = "SUBMISSIONS_CLOSED"
    IN_ARBITRATION = "IN_ARBITRATION"
    DETERMINED = "DETERMINED"


class ClearancePosture(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    CONDITIONAL = "CONDITIONAL"
    CONDITIONAL_WAIVED = "CONDITIONAL_WAIVED"
    ESCALATED = "ESCALATED"
    BLOCKED = "BLOCKED"


class AssignmentType(str, Enum):
    STORY = "STORY"
    TELEPLAY = "TELEPLAY"
    STORY_AND_TELEPLAY = "STORY_AND_TELEPLAY"
    REWRITE = "REWRITE"
    PRODUCTION_POLISH = "PRODUCTION_POLISH"


class AssignmentStatus(str, Enum):
    DRAFTING = "DRAFTING"
    DELIVERED = "DELIVERED"
    IN_NOTES = "IN_NOTES"
    REASSIGNMENT_PENDING = "REASSIGNMENT_PENDING"
    APPROVED = "APPROVED"
    VOID = "VOID"


class MilestoneType(str, Enum):
    OUTLINE = "OUTLINE"
    FIRST_DRAFT = "FIRST_DRAFT"
    SECOND_DRAFT = "SECOND_DRAFT"
    PRODUCTION_POLISH = "PRODUCTION_POLISH"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    LATE = "LATE"
    DELIVERED = "DELIVERED"
    NOTES_ISSUED = "NOTES_ISSUED"
    ACCEPTED = "ACCEPTED"


class ClearanceItemType(str, Enum):
    NAME = "NAME"
    TRADEMARK = "TRADEMARK"
    DEPICTION = "DEPICTION"


class ClearanceDecision(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    CONDITIONAL = "CONDITIONAL"
    BLOCKED = "BLOCKED"


class ClaimBasis(str, Enum):
    WRITTEN_BY = "WRITTEN_BY"
    STORY_BY = "STORY_BY"
    TELEPLAY_BY = "TELEPLAY_BY"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class ArbitrationStatus(str, Enum):
    INITIATED = "INITIATED"
    STATEMENTS_OPEN = "STATEMENTS_OPEN"
    PANEL_VOTING = "PANEL_VOTING"
    DEADLOCKED = "DEADLOCKED"
    DETERMINED = "DETERMINED"
    POLICY_REVIEW = "POLICY_REVIEW"


class ArbitrationOutcome(str, Enum):
    NONE = "NONE"
    UPHELD = "UPHELD"
    REVISED = "REVISED"
    DEADLOCK_RESOLVED_BY_POLICY = "DEADLOCK_RESOLVED_BY_POLICY"


class LedgerEntryType(str, Enum):
    SCRIPT_FEE_ACCRUAL = "SCRIPT_FEE_ACCRUAL"
    GUARANTEE_OFFSET = "GUARANTEE_OFFSET"
    GUARANTEE_REALLOCATION = "GUARANTEE_REALLOCATION"
    FEE_REVERSAL = "FEE_REVERSAL"


class ApprovedByRole(str, Enum):
    SHOWRUNNER = "SHOWRUNNER"
    STUDIO_EXECUTIVE = "STUDIO_EXECUTIVE"


# --- Common field mix-ins ----------------------------------------------------

class CommonFields(TypedDict):
    """The quartet carried by every entity except the append-only ledger row."""

    id: str
    created_at: str
    updated_at: str
    version: int


class LedgerCommonFields(TypedDict):
    """Fee ledger rows are immutable, so they carry only id and created_at."""

    id: str
    created_at: str


# --- Entities ----------------------------------------------------------------

class GuildAgreement(CommonFields):
    mba_year: int
    min_weekly_cents_by_level: Dict[str, int]
    script_fee_cents_by_length: Dict[str, int]
    type_share_pct_by_assignment_type: Dict[str, float]
    guarantee_offset_pct_by_level: Dict[str, float]
    level_credit_thresholds: Dict[str, int]
    diversity_subsidy_pct: float
    diversity_subsidy_cap_weekly_cents: int
    mini_room_floor_multiplier: float
    short_commitment_weeks_threshold: int
    short_commitment_uplift_pct: float
    facility_fee_tiers: Dict[str, int]
    facility_tier_subtotal_bounds: Dict[str, int]
    format_surcharge_pct: Dict[str, float]
    max_free_revision_rounds: int
    credit_share_threshold_pct: int
    arbitration_concurrence_pct: float
    arbitration_concurrence_band_pct: int
    outline_lead_days: int
    first_draft_lead_days: int
    second_draft_lead_days: int
    polish_lead_days: int
    turnaround_buffer_days: int
    clearance_item_weights: Dict[str, int]
    clearance_escalation_score: int


class Writer(CommonFields):
    legal_name: str
    guild_member_id: str
    career_episodic_credits: int
    diversity_program_participant: bool
    is_showrunner_eligible: bool
    determined_level: str
    level_determination_agreement_id: str
    active_seat_count: int
    on_screen_credit_count: int


class AvailabilityWindow(CommonFields):
    writer_id: str
    start_date: str
    end_date: str
    commitment_type: str
    status: str
    consumed_by_seat_id: Optional[str]


class Season(CommonFields):
    guild_agreement_id: str
    showrunner_writer_id: str
    title: str
    episode_order: int
    length_format: str
    production_start_date: str
    staffing_window_start: str
    staffing_window_end: str
    ready_script_target: int
    guarantee_application_mode: str
    staffing_budget_weekly_cents: int
    script_fee_budget_cents: int
    staffing_commitment_weekly_cents: int
    script_fee_committed_cents: int
    ready_script_count: int
    coverage_posture: str
    coverage_gap: int


class WritersRoom(CommonFields):
    season_id: str
    name: str
    format: str
    seat_capacity: int
    duration_weeks_committed: int
    start_date: str
    end_date: str
    diversity_seats_required: int
    status: str
    filled_seat_count: int
    confirmed_seat_count: int
    open_seat_count: int
    confirmed_diversity_seat_count: int
    seat_subtotal_weekly_cents: int
    facility_tier: str
    facility_surcharge_weekly_cents: int
    weekly_burn_cents: int


class RoomSeat(CommonFields):
    room_id: str
    writer_id: str
    level_at_hire: str
    offered_weekly_compensation_cents: int
    exclusivity: str
    start_date: str
    end_date: str
    episodic_guarantee_count: int
    diversity_program_funded: bool
    weekly_compensation_cents: int
    guild_floor_weekly_cents: int
    diversity_subsidy_weekly_cents: int
    studio_charge_weekly_cents: int
    prorated_commitment_cents: int
    guarantee_slots_consumed: int
    guarantee_slots_remaining: int
    status: str
    confirmed_at: Optional[str]
    consumed_window_id: Optional[str]


class Episode(CommonFields):
    season_id: str
    episode_number: int
    length_format: str
    production_unit: str
    production_start_date: str
    shoot_days: int
    script_readiness: str
    credit_status: str
    clearance_posture: str
    approved_teleplay_assignment_id: Optional[str]
    provisional_credit_shares: Optional[Dict[str, int]]
    final_credit_shares: Optional[Dict[str, int]]
    determined_credit_string: Optional[str]
    locked_at: Optional[str]


class ScriptAssignment(CommonFields):
    episode_id: str
    writer_id: str
    room_seat_id: Optional[str]
    predecessor_assignment_id: Optional[str]
    assignment_type: str
    gross_fee_cents: int
    guarantee_slot_applied: bool
    guarantee_offset_cents: int
    payable_fee_cents: int
    revision_round: int
    status: str
    outline_due_date: str
    first_draft_due_date: str
    second_draft_due_date: str
    polish_due_date: str
    late_milestone_count: int
    approved_at: Optional[str]
    approved_by_role: Optional[str]


class Milestone(CommonFields):
    assignment_id: str
    milestone_type: str
    sequence_index: int
    due_date: str
    delivered_at: Optional[str]
    days_late: int
    status: str


class ClearanceReview(CommonFields):
    assignment_id: str
    reviewed_draft_milestone_id: str
    item_count: int
    decided_item_count: int
    risk_score: int
    posture: str
    legal_waiver_granted: bool
    waiver_memo: Optional[str]


class ClearanceItem(CommonFields):
    review_id: str
    item_type: str
    descriptor: str
    scene_reference: str
    decision: str
    risk_weight: int
    conditional_note: Optional[str]


class CreditSubmission(CommonFields):
    episode_id: str
    writer_id: str
    claim_basis: str
    claimed_contribution_pct: int
    status: str
    provisional_share_pct: Optional[int]
    arbitrated_share_pct: Optional[int]
    receives_credit: bool


class CreditArbitration(CommonFields):
    episode_id: str
    arbiter_writer_ids: List[str]
    participant_writer_ids: List[str]
    status: str
    votes_cast_count: int
    vote_ledger: Dict[str, Dict[str, int]]
    leading_writer_id: Optional[str]
    concurrence_pct: Optional[float]
    outcome: str
    determined_credit_string: Optional[str]


class FeeLedgerEntry(LedgerCommonFields):
    """Append-only money row: no updated_at and no version field at all."""

    season_id: str
    assignment_id: str
    writer_id: str
    entry_type: str
    amount_cents: int
    memo: str


# --- Envelope helpers --------------------------------------------------------

class PaginationMeta(TypedDict):
    api_request_id: str
    api_request_timestamp: str
    total_count: int
    has_more: bool
    limit: int
    offset: int


JsonDict = Dict[str, Any]
