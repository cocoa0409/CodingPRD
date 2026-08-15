"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity catalogue (PRD §3). Every resource carries the
standard system-managed fields id / created_at / updated_at / version (PRD §2.6).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    VOLUNTEER = "Volunteer"
    CAPTAIN = "Captain"
    GROUP_LEADER = "GroupLeader"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    EVENT_DIRECTOR = "EventDirector"


# ---------------------------------------------------------------------------
# Status / vocabulary enums
# ---------------------------------------------------------------------------

class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    RACE_DAY = "RACE_DAY"
    COMPLETED = "COMPLETED"
    DEBRIEF_OPEN = "DEBRIEF_OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TerrainType(str, Enum):
    ROAD = "ROAD"
    TRAIL = "TRAIL"
    BRIDGE = "BRIDGE"
    TRACK = "TRACK"


class RequiredSkill(str, Enum):
    NONE = "NONE"
    MEDICAL = "MEDICAL"
    BIKE_MARSHAL = "BIKE_MARSHAL"
    TIMING_TECH = "TIMING_TECH"
    COURSE_MARSHAL = "COURSE_MARSHAL"


class TrainingModule(str, Enum):
    NONE = "NONE"
    SAFETY_BRIEFING = "SAFETY_BRIEFING"
    MEDICAL_RESPONSE = "MEDICAL_RESPONSE"
    CAPTAIN_COURSE = "CAPTAIN_COURSE"


class SkillTag(str, Enum):
    MEDICAL = "MEDICAL"
    BIKE_MARSHAL = "BIKE_MARSHAL"
    TIMING_TECH = "TIMING_TECH"
    COURSE_MARSHAL = "COURSE_MARSHAL"


class RoleEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    LOCKED = "LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class GroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VolunteerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"


class TrainingRecordStatus(str, Enum):
    ENROLLED = "ENROLLED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class SignupStatus(str, Enum):
    REQUESTED = "REQUESTED"
    WAITLISTED = "WAITLISTED"
    APPROVED = "APPROVED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class SignupOrigin(str, Enum):
    DIRECT = "DIRECT"
    WAITLIST_PROMOTION = "WAITLIST_PROMOTION"
    FLOAT_POOL_BACKFILL = "FLOAT_POOL_BACKFILL"


class DistributionKind(str, Enum):
    CREDENTIAL = "CREDENTIAL"
    SUPPLY_ITEM = "SUPPLY_ITEM"


class DistributionStatus(str, Enum):
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    REVOKED = "REVOKED"


class HourLogStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"


class VerifiedByRole(str, Enum):
    CAPTAIN = "CAPTAIN"
    COORDINATOR = "COORDINATOR"


class DebriefStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class AdjustmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


class RecognitionTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all entities carry common fields (PRD §2.6)
# ---------------------------------------------------------------------------

class Event(TypedDict, total=False):
    id: str
    name: str
    event_start_at: str
    event_end_at: str
    early_access_opens_at: str
    signup_opens_at: str
    signup_closes_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CourseSegment(TypedDict, total=False):
    id: str
    event_id: str
    segment_code: str
    mile_start: float
    mile_end: float
    terrain_type: str
    created_at: str
    updated_at: str
    version: int


class RoleCatalogEntry(TypedDict, total=False):
    id: str
    event_id: str
    role_code: str
    title: str
    min_age_years: int
    required_skill: str
    required_training_module: str
    credit_weight: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    event_id: str
    role_entry_id: str
    segment_id: str
    start_at: str
    end_at: str
    required_headcount: int
    confirmed_count: int
    checked_in_count: int
    understaffed_alert: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FundraisingGroup(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    charity_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    event_id: str
    group_id: Optional[str]
    full_name: str
    date_of_birth: str
    skill_tags: List[str]
    float_opt_in: bool
    is_returning: bool
    status: str
    age_years_on_event: int
    no_show_strikes: int
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    event_id: str
    volunteer_id: str
    module_code: str
    status: str
    passed_at: Optional[str]
    valid_until: Optional[str]
    attempt_count: int
    created_at: str
    updated_at: str
    version: int


class Signup(TypedDict, total=False):
    id: str
    event_id: str
    volunteer_id: str
    shift_id: str
    status: str
    origin: str
    replaces_signup_id: Optional[str]
    is_captain: bool
    requested_at: str
    approved_at: Optional[str]
    confirm_by_at: Optional[str]
    confirmed_at: Optional[str]
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplyInventory(TypedDict, total=False):
    id: str
    event_id: str
    item_code: str
    description: str
    quantity_total: int
    quantity_issued: int
    created_at: str
    updated_at: str
    version: int


class DistributionRecord(TypedDict, total=False):
    id: str
    event_id: str
    signup_id: str
    inventory_id: Optional[str]
    kind: str
    status: str
    issued_at: str
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HourLog(TypedDict, total=False):
    id: str
    event_id: str
    signup_id: str
    status: str
    break_minutes: int
    raw_minutes: int
    claimed_hours: float
    credited_hours: float
    verified_by_role: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DebriefReport(TypedDict, total=False):
    id: str
    event_id: str
    shift_id: str
    author_volunteer_id: str
    headcount_actual: int
    role_effectiveness_rating: int
    supply_shortage_flag: bool
    notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RoleAdjustment(TypedDict, total=False):
    id: str
    event_id: str
    role_entry_id: str
    debrief_report_id: str
    proposed_min_age_years: Optional[int]
    proposed_required_skill: Optional[str]
    proposed_credit_weight: Optional[float]
    proposed_retire: bool
    status: str
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditSummary(TypedDict, total=False):
    provisional_effective_hours: float
    settled_effective_hours: float
    provisional_credit_cents: int
    settled_credit_cents: int
    sponsor_match_cents: int
    total_settled_credit_cents: int


class RecognitionSummary(TypedDict, total=False):
    projected_points: int
    official_points: int
    recognition_tier: str
    captain_shift_count: int
    no_show_count: int


class EpochSweepResult(TypedDict, total=False):
    expired_training_record_ids: List[str]
    auto_locked: bool
    timed_out_signup_ids: List[str]
