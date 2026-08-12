"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the standard system-managed fields
(id, created_at, updated_at, version) described in PRD section "Common
Resource Properties".
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status / state enums
# ---------------------------------------------------------------------------

class MeetPosture(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    WARMUP_OPEN = "WARMUP_OPEN"
    IN_COMPETITION = "IN_COMPETITION"
    SCORING_CLOSED = "SCORING_CLOSED"
    FINALIZED = "FINALIZED"
    ARCHIVED = "ARCHIVED"


class SessionState(str, Enum):
    SCHEDULED = "SCHEDULED"
    WARMUP_OPEN = "WARMUP_OPEN"
    MARCH_IN = "MARCH_IN"
    IN_ROTATION = "IN_ROTATION"
    SCORING = "SCORING"
    CLOSED = "CLOSED"


class EntryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    SCRATCHED = "SCRATCHED"
    COMPETING = "COMPETING"
    COMPLETED = "COMPLETED"


class CredentialState(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    CREDENTIALED = "CREDENTIALED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class PassState(str, Enum):
    ISSUED = "ISSUED"
    FLOOR_ACCESS_GRANTED = "FLOOR_ACCESS_GRANTED"
    FLOOR_ACCESS_SUSPENDED = "FLOOR_ACCESS_SUSPENDED"
    REVOKED = "REVOKED"


class PanelState(str, Enum):
    FORMING = "FORMING"
    FULL = "FULL"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class AssignmentState(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    RECUSED = "RECUSED"
    RELEASED = "RELEASED"


class RotationState(str, Enum):
    PENDING = "PENDING"
    WARMUP = "WARMUP"
    TIMED_WARMUP_HELD = "TIMED_WARMUP_HELD"
    OPEN_FOR_SCORING = "OPEN_FOR_SCORING"
    SCORING_CLOSED = "SCORING_CLOSED"
    FINALIZED = "FINALIZED"


class WarmupBlockState(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    SKIPPED = "SKIPPED"


class ScoreState(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    UNDER_INQUIRY = "UNDER_INQUIRY"
    INQUIRY_RESOLVED = "INQUIRY_RESOLVED"
    FINAL = "FINAL"
    VOID = "VOID"


class InquiryState(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class TicketState(str, Enum):
    ISSUED = "ISSUED"
    SCANNED = "SCANNED"
    REDEEMED = "REDEEMED"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class QualificationState(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"


class Apparatus(str, Enum):
    VAULT = "VAULT"
    UNEVEN_BARS = "UNEVEN_BARS"
    BALANCE_BEAM = "BALANCE_BEAM"
    FLOOR_EXERCISE = "FLOOR_EXERCISE"


class LevelBand(str, Enum):
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"
    L6 = "L6"
    L7 = "L7"
    L8 = "L8"
    L9 = "L9"
    L10 = "L10"
    XCEL_BRONZE = "XCEL_BRONZE"
    XCEL_SILVER = "XCEL_SILVER"
    XCEL_GOLD = "XCEL_GOLD"
    XCEL_PLATINUM = "XCEL_PLATINUM"
    XCEL_DIAMOND = "XCEL_DIAMOND"


class JudgeRating(str, Enum):
    BREVET = "BREVET"
    NATIONAL = "NATIONAL"
    USA = "USA"
    LEVEL_10 = "LEVEL_10"
    LEVEL_9 = "LEVEL_9"
    LEVEL_8 = "LEVEL_8"
    LEVEL_7 = "LEVEL_7"
    LEVEL_4_5 = "LEVEL_4_5"
    XCEL = "XCEL"


class PanelRole(str, Enum):
    PANEL_CHIEF = "PANEL_CHIEF"
    D_JUDGE = "D_JUDGE"
    E_JUDGE = "E_JUDGE"
    LINE_JUDGE = "LINE_JUDGE"
    TIMER = "TIMER"


class TicketClass(str, Enum):
    GENERAL_ADMISSION = "GENERAL_ADMISSION"
    RESERVED = "RESERVED"
    VIP = "VIP"
    COMP = "COMP"


class AwardCategory(str, Enum):
    VAULT = "VAULT"
    UNEVEN_BARS = "UNEVEN_BARS"
    BALANCE_BEAM = "BALANCE_BEAM"
    FLOOR_EXERCISE = "FLOOR_EXERCISE"
    ALL_AROUND = "ALL_AROUND"


class TargetMeetLevel(str, Enum):
    STATE = "STATE"
    REGIONAL = "REGIONAL"
    NATIONAL = "NATIONAL"


class UserRole(str, Enum):
    MEET_DIRECTOR = "MeetDirector"
    MEET_REFEREE = "MeetReferee"
    JUDGE_PANEL_CHIEF = "JudgePanelChief"
    COACH = "Coach"
    GATE_ATTENDANT = "GateAttendant"
    SPECTATOR = "Spectator"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Meet(TypedDict, total=False):
    id: str
    meet_name: str
    sanction_year: int
    sanction_number: str
    venue_name: str
    start_date: str
    end_date: str
    posture: str
    tiebreak_policy: str
    qualifying_score_rule: str
    inquiry_window_minutes: int
    max_athletes_per_squad: int
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    meet_id: str
    session_label: str
    level_band: str
    scheduled_start: str
    scheduled_end: str
    warmup_open_offset_minutes: int
    march_in_offset_minutes: int
    apparatus_set: List[dict]
    state: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Squad(TypedDict, total=False):
    id: str
    session_id: str
    squad_label: str
    starting_apparatus: str
    rotation_index: int
    athlete_count: int
    created_at: str
    updated_at: str
    version: int


class Gymnast(TypedDict, total=False):
    id: str
    usag_member_number: str
    legal_name: str
    date_of_birth: str
    competitive_level: str
    home_gym: str
    created_at: str
    updated_at: str
    version: int


class AthleteEntry(TypedDict, total=False):
    id: str
    session_id: str
    gymnast_id: str
    squad_id: Optional[str]
    entry_status: str
    scratch_reason: Optional[str]
    all_around_total: float
    all_around_rank: Optional[int]
    qualified_for_next_meet: bool
    qualification_mobility_score: float
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict, total=False):
    id: str
    usag_coach_number: str
    legal_name: str
    affiliated_gym: str
    background_check_expiry: str
    safety_cert_expiry: str
    credential_state: str
    created_at: str
    updated_at: str
    version: int


class CoachMeetPass(TypedDict, total=False):
    id: str
    meet_id: str
    coach_id: str
    pass_state: str
    issued_at: str
    floor_access_granted_at: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Judge(TypedDict, total=False):
    id: str
    usag_judge_number: str
    legal_name: str
    rating: str
    affiliated_gym: str
    availability_start: str
    availability_end: str
    created_at: str
    updated_at: str
    version: int


class JudgePanel(TypedDict, total=False):
    id: str
    meet_id: str
    session_id: str
    apparatus: str
    panel_state: str
    required_judge_count: int
    created_at: str
    updated_at: str
    version: int


class PanelAssignment(TypedDict, total=False):
    id: str
    judge_panel_id: str
    judge_id: str
    role: str
    assignment_state: str
    conflict_flag: bool
    created_at: str
    updated_at: str
    version: int


class Rotation(TypedDict, total=False):
    id: str
    session_id: str
    rotation_number: int
    apparatus: str
    scheduled_start: str
    scheduled_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class WarmupBlock(TypedDict, total=False):
    id: str
    rotation_id: str
    squad_id: str
    apparatus: str
    block_start: str
    block_end: str
    state: str
    created_at: str
    updated_at: str
    version: int


class Score(TypedDict, total=False):
    id: str
    athlete_entry_id: str
    rotation_id: str
    apparatus: str
    difficulty_score: float
    execution_score: float
    neutral_deduction: float
    provisional_total: float
    final_total: float
    score_state: str
    published_at: Optional[str]
    finalized_at: Optional[str]
    is_tied: bool
    tiebreak_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Inquiry(TypedDict, total=False):
    id: str
    score_id: str
    filed_by_coach_id: str
    filed_at: str
    inquiry_state: str
    resolution: Optional[str]
    d_score_delta: float
    e_score_delta: float
    deduction_delta: float
    resolved_at: Optional[str]
    resolution_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    session_id: str
    category: str
    place: int
    athlete_entry_id: str
    awarded_at: str
    ceremony_order: int
    was_tiebroken: bool
    created_at: str
    updated_at: str
    version: int


class SpectatorTicket(TypedDict, total=False):
    id: str
    meet_id: str
    session_id: str
    holder_name: str
    holder_email: str
    ticket_class: str
    seat_section: Optional[str]
    price_cents: int
    ticket_state: str
    scanned_at: Optional[str]
    redeemed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualificationRecord(TypedDict, total=False):
    id: str
    athlete_entry_id: str
    target_meet_level: str
    qualifying_score_used: float
    threshold_applied: float
    qualification_state: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
