"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the four system-managed fields (id, created_at,
updated_at, version) per the PRD's common-resource-properties rule.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CONTESTANT = "Contestant"
    CONTEST_LEAD = "ContestLead"
    JUDGE = "Judge"
    SAFETY_OFFICER = "SafetyOfficer"
    STAGE_MANAGER = "StageManager"
    TREASURER = "Treasurer"


class ContestStatus(str, Enum):
    SETUP = "SETUP"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    JUDGING = "JUDGING"
    TABULATION = "TABULATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CategoryStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SCORING = "SCORING"
    TABULATED = "TABULATED"


class SkillDivision(str, Enum):
    JUNIOR = "JUNIOR"
    NOVICE = "NOVICE"
    JOURNEYMAN = "JOURNEYMAN"
    MASTERS = "MASTERS"


class TabulationMethod(str, Enum):
    WEIGHTED_MEAN = "WEIGHTED_MEAN"
    TRIMMED_MEAN = "TRIMMED_MEAN"


class EntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SAFETY_REJECTED = "SAFETY_REJECTED"
    SAFETY_APPROVED = "SAFETY_APPROVED"
    PREJUDGED = "PREJUDGED"
    STAGE_QUEUED = "STAGE_QUEUED"
    PERFORMED = "PERFORMED"
    PLACED = "PLACED"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class SafetyStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PreJudgingSlotStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"


class ScoreSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"
    VOID = "VOID"


class ScorePhase(str, Enum):
    CRAFTSMANSHIP = "CRAFTSMANSHIP"
    STAGE = "STAGE"


class PerformanceSlotStatus(str, Enum):
    QUEUED = "QUEUED"
    ON_STAGE = "ON_STAGE"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class PrizeAwardStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    TAX_REPORTED = "TAX_REPORTED"
    REVOKED = "REVOKED"


class GreenRoomBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class RoomName(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"


class ConsentScope(str, Enum):
    PHOTOGRAPHY = "PHOTOGRAPHY"
    VIDEO = "VIDEO"
    LIVESTREAM = "LIVESTREAM"


class ConsentStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class ConsentItem(TypedDict, total=False):
    scope: str
    status: str
    updated_at: str


class ContestEvent(TypedDict, total=False):
    id: str
    name: str
    start_at: str
    end_at: str
    prize_budget_cents: int
    max_entries_per_contestant: int
    status: str
    budget_reserved_cents: int
    budget_available_cents: int
    created_at: str
    updated_at: str
    version: int


class Category(TypedDict, total=False):
    id: str
    contest_id: str
    name: str
    skill_division: str
    max_entries: int
    tabulation_method: str
    prize_purse_cents: int
    status: str
    entry_count: int
    prize_rank1_cents: int
    prize_rank2_cents: int
    prize_rank3_cents: int
    created_at: str
    updated_at: str
    version: int


class Contestant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    birth_date: str
    accessibility_needs: List[str]
    consents: List[ConsentItem]
    created_at: str
    updated_at: str
    version: int


class Judge(TypedDict, total=False):
    id: str
    contest_id: str
    display_name: str
    category_ids: List[str]
    linked_contestant_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Entry(TypedDict, total=False):
    id: str
    contestant_id: str
    category_id: str
    contest_id: str
    title: str
    character_source: str
    prop_declarations: List[str]
    requires_prejudging: bool
    status: str
    safety_status: str
    rejected_props: List[str]
    placement_rank: Optional[int]
    final_score: Optional[float]
    craftsmanship_mean: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PreJudgingSlot(TypedDict, total=False):
    id: str
    category_id: str
    panel_name: str
    start_at: str
    end_at: str
    status: str
    booked_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScoreSheet(TypedDict, total=False):
    id: str
    entry_id: str
    judge_id: str
    category_id: str
    phase: str
    craftsmanship: int
    accuracy: int
    presentation: int
    sheet_total: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceSlot(TypedDict, total=False):
    id: str
    entry_id: str
    contest_id: str
    sequence_number: int
    duration_seconds: int
    tech_cues: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PrizeAward(TypedDict, total=False):
    id: str
    category_id: str
    contest_id: str
    rank: int
    entry_id: str
    value_cents: int
    tax_reportable: bool
    tax_form_received: bool
    withheld_cents: Optional[int]
    net_payout_cents: Optional[int]
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GreenRoomBooking(TypedDict, total=False):
    id: str
    contestant_id: str
    contest_id: str
    room_name: str
    start_at: str
    end_at: str
    requires_accessibility_setup: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxSummary(TypedDict, total=False):
    total_prize_value_cents: int
    total_withheld_cents: int
    reportable_award_count: int
    disbursed_award_count: int
