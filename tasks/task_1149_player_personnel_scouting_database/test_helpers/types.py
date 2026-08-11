"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD §2.4 common fields plus each entity's own
fields from PRD §3.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ScoutLevel(str, Enum):
    AREA = "AREA"
    DIRECTOR = "DIRECTOR"


class EvaluationStatus(str, Enum):
    NEW = "NEW"
    SCOUTING = "SCOUTING"
    EVALUATED = "EVALUATED"
    BOARD_READY = "BOARD_READY"
    DRAFTED = "DRAFTED"
    ARCHIVED = "ARCHIVED"


class FlagStatus(str, Enum):
    CLEAR = "CLEAR"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLEARED = "CLEARED"
    EXCLUDED = "EXCLUDED"


class Tier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    LOCKED = "LOCKED"


class VideoTagCategory(str, Enum):
    SCHEME = "SCHEME"
    ATHLETICISM = "ATHLETICISM"
    TECHNIQUE = "TECHNIQUE"
    CHARACTER = "CHARACTER"


class FlagType(str, Enum):
    MEDICAL = "MEDICAL"
    CHARACTER = "CHARACTER"


class FlagSeverity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class FlagLifecycle(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class BoardStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    FINALIZED = "FINALIZED"


class PriorityTier(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class RosterNeedStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TargetStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    EVALUATING = "EVALUATING"
    APPROVED = "APPROVED"
    OFFERED = "OFFERED"
    SIGNED = "SIGNED"
    RELEASED = "RELEASED"
    PASSED = "PASSED"


class BudgetPosture(str, Enum):
    HEALTHY = "HEALTHY"
    TIGHT = "TIGHT"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    AREA_SCOUT = "AreaScout"
    SCOUTING_DIRECTOR = "ScoutingDirector"
    MEDICAL_STAFF = "MedicalStaff"
    GENERAL_MANAGER = "GeneralManager"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 common fields; VideoTag is the sole exception)
# ---------------------------------------------------------------------------


class Scout(TypedDict, total=False):
    id: str
    full_name: str
    level: str
    weight: float
    season_grade_mean: Optional[float]
    season_grade_stdev: Optional[float]
    locked_grade_mean: Optional[float]
    locked_grade_stdev: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Prospect(TypedDict, total=False):
    id: str
    full_name: str
    position: str
    college: str
    evaluation_status: str
    flag_status: str
    composite_grade: Optional[float]
    tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScoutingReport(TypedDict, total=False):
    id: str
    prospect_id: str
    scout_id: str
    raw_grade: float
    scheme_fit: float
    notes: str
    status: str
    normalized_grade: Optional[float]
    return_reason: str
    created_at: str
    updated_at: str
    version: int


class VideoTag(TypedDict, total=False):
    # PRD §2.4: carries id and created_at only — no updated_at, no version.
    id: str
    report_id: str
    clip_url: str
    start_sec: int
    end_sec: int
    tag: str
    created_at: str


class ConfidentialFlag(TypedDict, total=False):
    id: str
    prospect_id: str
    flag_type: str
    severity: str
    detail: Optional[str]
    status: str
    author_role: str
    resolution_note: str
    created_at: str
    updated_at: str
    version: int


class DraftBoard(TypedDict, total=False):
    id: str
    season_year: int
    status: str
    active_entry_count: int
    created_at: str
    updated_at: str
    version: int


class DraftBoardEntry(TypedDict, total=False):
    id: str
    board_id: str
    prospect_id: str
    rank: int
    fit_score: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class RosterNeed(TypedDict, total=False):
    id: str
    season_year: int
    position: str
    priority_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FreeAgentTarget(TypedDict, total=False):
    id: str
    player_name: str
    position: str
    season_year: int
    base_salary_cents: int
    signing_bonus_cents: int
    contract_years: int
    status: str
    annual_cap_hit_cents: int
    signed_budget_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Budget(TypedDict, total=False):
    id: str
    season_year: int
    base_cap_cents: int
    rollover_cents: int
    committed_cents: int
    available_cents: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class InterviewSession(TypedDict, total=False):
    id: str
    prospect_id: str
    start_at: str
    end_at: str
    location: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class FacilityBooking(TypedDict, total=False):
    id: str
    facility_id: str
    start_at: str
    end_at: str
    purpose: str
    created_at: str
    updated_at: str
    version: int


class OutcomeRecord(TypedDict, total=False):
    id: str
    prospect_id: str
    season_year: int
    games_started: int
    pro_bowl: bool
    outcome_percentile: int
    created_at: str
    updated_at: str
    version: int
