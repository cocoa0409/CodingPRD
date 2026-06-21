"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class OrganizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class VolunteerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class BgCheckTier(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"


class MilestoneTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class BackgroundCheckStatus(str, Enum):
    INITIATED = "INITIATED"
    IN_PROGRESS = "IN_PROGRESS"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ProficiencyLevel(str, Enum):
    SELF_DECLARED = "SELF_DECLARED"
    VERIFIED = "VERIFIED"


class PublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class StaffingStatus(str, Enum):
    UNDERSTAFFED = "UNDERSTAFFED"
    FULLY_STAFFED = "FULLY_STAFFED"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class SignupStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    ATTENDED = "ATTENDED"
    HOURS_LOGGED = "HOURS_LOGGED"
    HOURS_VERIFIED = "HOURS_VERIFIED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CorporateGroupStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ALLOCATED = "ALLOCATED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    VOLUNTEER = "Volunteer"
    SHIFT_COORDINATOR = "ShiftCoordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CORPORATE_SPONSOR = "CorporateSponsor"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Entities with common_fields:true carry id, created_at, updated_at, version.

class Organization(TypedDict):
    id: str
    name: str
    reliability_suspension_threshold: int
    no_show_strike_limit: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    organization_id: str
    full_name: str
    email: str
    status: str
    bg_check_tier: str
    lifetime_no_show_count: int
    total_verified_hours: float
    reliability_score: int
    milestone_tier: str
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict):
    id: str
    volunteer_id: str
    requested_tier: str
    status: str
    cleared_at: Optional[str]
    valid_until: Optional[str]
    validity_days: int
    created_at: str
    updated_at: str
    version: int


class Skill(TypedDict):
    id: str
    organization_id: str
    code: str
    label: str
    created_at: str
    updated_at: str
    version: int


class WaiverTemplate(TypedDict):
    id: str
    organization_id: str
    code: str
    revision: int
    created_at: str
    updated_at: str
    version: int


class TrainingModule(TypedDict):
    id: str
    organization_id: str
    code: str
    valid_days: int
    created_at: str
    updated_at: str
    version: int


class Opportunity(TypedDict):
    id: str
    organization_id: str
    title: str
    publication_status: str
    staffing_status: str
    required_bg_tier: str
    required_skill_ids: List[str]
    required_waiver_template_id: Optional[str]
    required_training_module_id: Optional[str]
    is_group_event: bool
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    opportunity_id: str
    starts_at: str
    ends_at: str
    capacity: int
    reserved_count: int
    status: str
    group_reserved_seats: int
    created_at: str
    updated_at: str
    version: int


class Signup(TypedDict):
    id: str
    shift_id: str
    volunteer_id: str
    corporate_group_id: Optional[str]
    status: str
    logged_hours: Optional[float]
    verified_hours: Optional[float]
    provisional_hours: float
    created_at: str
    updated_at: str
    version: int


class CorporateGroup(TypedDict):
    id: str
    opportunity_id: str
    sponsor_name: str
    requested_seats: int
    target_shift_id: str
    status: str
    allocated_seat_count: int
    created_at: str
    updated_at: str
    version: int


# Entities with common_fields:false — append-only, carry ONLY id + created_at
# (no updated_at, no version).

class VolunteerSkill(TypedDict):
    id: str
    volunteer_id: str
    skill_id: str
    proficiency: str
    created_at: str


class WaiverAcceptance(TypedDict):
    id: str
    volunteer_id: str
    waiver_template_id: str
    accepted_revision: int
    created_at: str


class TrainingCompletion(TypedDict):
    id: str
    volunteer_id: str
    training_module_id: str
    completed_at: str
    expires_at: str
    created_at: str
