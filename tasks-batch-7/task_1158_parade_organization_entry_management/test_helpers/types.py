"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COMMITTEE_ADMIN = "CommitteeAdmin"
    AGENCY_REVIEWER = "AgencyReviewer"
    SAFETY_INSPECTOR = "SafetyInspector"
    ENTRANT = "Entrant"
    JUDGE = "Judge"
    MARSHAL = "Marshal"


class ParadeStatus(str, Enum):
    DRAFT = "DRAFT"
    PERMIT_PENDING = "PERMIT_PENDING"
    PERMIT_GRANTED = "PERMIT_GRANTED"
    LOCKED = "LOCKED"
    LINEUP_PUBLISHED = "LINEUP_PUBLISHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ParadePosture(str, Enum):
    RESTRICTED = "RESTRICTED"
    OPERATIONAL = "OPERATIONAL"
    FROZEN = "FROZEN"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    AGENCY_REVIEW = "AGENCY_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class EndorsementStatus(str, Enum):
    PENDING = "PENDING"
    ENDORSED = "ENDORSED"
    REJECTED = "REJECTED"


class AgencyType(str, Enum):
    POLICE = "POLICE"
    FIRE = "FIRE"
    TRANSIT = "TRANSIT"
    SANITATION = "SANITATION"


class EntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class EntryCategory(str, Enum):
    FLOAT = "FLOAT"
    BAND = "BAND"
    WALKING_GROUP = "WALKING_GROUP"
    VEHICLE = "VEHICLE"
    EQUESTRIAN = "EQUESTRIAN"


class FloatCompliance(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class VehicleClass(str, Enum):
    SELF_PROPELLED = "SELF_PROPELLED"
    TOWED = "TOWED"
    PUSHED = "PUSHED"


class FuelType(str, Enum):
    GASOLINE = "GASOLINE"
    DIESEL = "DIESEL"
    ELECTRIC = "ELECTRIC"
    NONE = "NONE"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class LineupStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    RELEASED = "RELEASED"
    PULLED = "PULLED"
    NO_SHOW = "NO_SHOW"


class MarshalStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class SheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"


class AwardStatus(str, Enum):
    PENDING = "PENDING"
    ANNOUNCED = "ANNOUNCED"
    PRESENTED = "PRESENTED"
    CANCELLED = "CANCELLED"


class AwardCategory(str, Enum):
    BEST_FLOAT = "BEST_FLOAT"
    BEST_BAND = "BEST_BAND"
    BEST_WALKING = "BEST_WALKING"
    GRAND_PRIZE = "GRAND_PRIZE"


class SponsorTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"


class SponsorStatus(str, Enum):
    PLEDGED = "PLEDGED"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    DEFAULTED = "DEFAULTED"


class ScriptItemType(str, Enum):
    SPONSOR_READ = "SPONSOR_READ"
    ENTRY_INTRO = "ENTRY_INTRO"
    SAFETY_ANNOUNCEMENT = "SAFETY_ANNOUNCEMENT"
    AWARD_ANNOUNCEMENT = "AWARD_ANNOUNCEMENT"


class ScriptItemStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class DispersalPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ParadeEvent(TypedDict):
    id: str
    name: str
    parade_date: str
    entry_deadline: str
    status: str
    posture: str
    approved_entry_count: int
    sponsor_seconds_allocated: int
    script_finalized: bool
    created_at: str
    updated_at: str
    version: int


class RouteSegment(TypedDict):
    id: str
    parade_id: str
    order_index: int
    name: str
    length_meters: float
    emergency_lane_width_m: float
    segment_window_start: str
    segment_window_end: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    parade_id: str
    status: str
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    submitted_at: Optional[str]
    required_agency_count: int
    endorsed_count: int
    created_at: str
    updated_at: str
    version: int


class AgencyEndorsement(TypedDict):
    id: str
    permit_id: str
    agency_type: str
    status: str
    decided_at: Optional[str]
    permit_version: int
    created_at: str
    updated_at: str
    version: int


class EntryApplication(TypedDict):
    id: str
    parade_id: str
    applicant_user_id: str
    org_name: str
    requested_category: str
    assigned_category: Optional[str]
    estimated_participants: int
    status: str
    revision_count: int
    fee_cents: int
    fee_paid: bool
    provisional_score: Optional[float]
    final_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Float(TypedDict):
    id: str
    entry_id: str
    length_m: float
    width_m: float
    height_m: float
    weight_kg: float
    vehicle_class: str
    fuel_type: str
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class SafetyInspection(TypedDict):
    id: str
    float_id: str
    inspector_user_id: str
    scheduled_at: str
    status: str
    checklist_score: Optional[int]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StagingArea(TypedDict):
    id: str
    parade_id: str
    name: str
    capacity: int
    open_time: str
    close_time: str
    reserved_slots: int
    created_at: str
    updated_at: str
    version: int


class LineupAssignment(TypedDict):
    id: str
    parade_id: str
    entry_id: str
    staging_area_id: str
    position_number: int
    arrive_at: str
    depart_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MarshalAssignment(TypedDict):
    id: str
    parade_id: str
    route_segment_id: str
    marshal_user_id: str
    shift_start: str
    shift_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class JudgingScoreSheet(TypedDict):
    id: str
    entry_id: str
    judge_user_id: str
    creativity: int
    craftsmanship: int
    theme: int
    crowd_appeal: int
    sheet_total: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict):
    id: str
    parade_id: str
    award_category: str
    eligible_entry_category: str
    winner_entry_id: Optional[str]
    status: str
    announced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SponsorPackage(TypedDict):
    id: str
    parade_id: str
    sponsor_name: str
    tier: str
    contribution_cents: int
    status: str
    allocated_seconds: int
    created_at: str
    updated_at: str
    version: int


class AnnouncerScriptItem(TypedDict):
    id: str
    parade_id: str
    item_type: str
    sponsor_id: Optional[str]
    entry_id: Optional[str]
    sequence_index: int
    duration_minutes: float
    duration_seconds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DispersalPlan(TypedDict):
    id: str
    parade_id: str
    emergency_lane_width_m: float
    dispersal_corridors: List[str]
    evacuation_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
