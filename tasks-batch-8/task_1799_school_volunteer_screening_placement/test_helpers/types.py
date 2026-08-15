"""Domain types: entity TypedDicts, status enums, role enum.

Per the PRD's common-resource-properties rule, mutable resources (Volunteer,
BackgroundCheck, Opportunity, Placement, HourEntry, VisitCheckIn,
IncidentReport) carry id + created_at + updated_at + version, while
configuration and append-only resources (Campus, TrainingModule,
TrainingRecord, RecognitionAward) carry only id + created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    DISTRICT_COORDINATOR = "DistrictCoordinator"
    CAMPUS_ADMIN = "CampusAdmin"
    VOLUNTEER = "Volunteer"


class ContactType(str, Enum):
    SUPERVISED = "SUPERVISED"
    UNSUPERVISED = "UNSUPERVISED"


class CheckLevel(str, Enum):
    BASIC = "BASIC"
    ENHANCED = "ENHANCED"


class Findings(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    DISQUALIFYING = "DISQUALIFYING"


class VolunteerStatus(str, Enum):
    APPLIED = "APPLIED"
    UNDER_SCREENING = "UNDER_SCREENING"
    CLEARANCE_GRANTED = "CLEARANCE_GRANTED"
    ACTIVE = "ACTIVE"
    RESCREEN_REQUIRED = "RESCREEN_REQUIRED"
    SUSPENDED = "SUSPENDED"
    DENIED = "DENIED"
    REMOVED = "REMOVED"


class BackgroundCheckStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    CLEARED_WITH_FLAGS = "CLEARED_WITH_FLAGS"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class OpportunityStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PlacementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class CancelReason(str, Enum):
    VOLUNTEER_WITHDRAW = "VOLUNTEER_WITHDRAW"
    ADMIN_CANCEL = "ADMIN_CANCEL"
    SYSTEM_SUSPENSION = "SYSTEM_SUSPENSION"
    SYSTEM_RESTRICTION = "SYSTEM_RESTRICTION"
    SYSTEM_REMOVAL = "SYSTEM_REMOVAL"
    OPPORTUNITY_CANCELLED = "OPPORTUNITY_CANCELLED"


class HourEntryStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class ActivityCategory(str, Enum):
    STANDARD = "STANDARD"
    TUTORING = "TUTORING"
    MENTORING = "MENTORING"


class CheckInStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CloseReason(str, Enum):
    SELF = "SELF"
    ADMIN = "ADMIN"
    SYSTEM_SUSPENSION = "SYSTEM_SUSPENSION"
    SYSTEM_REMOVAL = "SYSTEM_REMOVAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNFOUNDED = "UNFOUNDED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RestrictedCategory(str, Enum):
    NONE = "NONE"
    TRANSPORT = "TRANSPORT"
    ONE_ON_ONE = "ONE_ON_ONE"


class RestrictionFlag(str, Enum):
    NO_TRANSPORT = "NO_TRANSPORT"
    NO_ONE_ON_ONE = "NO_ONE_ON_ONE"


class RecognitionTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AwardSource(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


# --- Configuration / append-only resources: id + created_at only ---

class Campus(TypedDict, total=False):
    id: str
    name: str
    campus_code: str
    badge_prefix: str
    created_at: str


class TrainingModule(TypedDict, total=False):
    id: str
    module_code: str
    title: str
    required_contact_types: List[str]
    validity_days: Optional[int]
    created_at: str


class TrainingRecord(TypedDict, total=False):
    id: str
    volunteer_id: str
    module_id: str
    completed_at: str
    expires_at: Optional[str]
    created_at: str


class RecognitionAward(TypedDict, total=False):
    id: str
    volunteer_id: str
    tier: str
    source: str
    note: str
    created_at: str


# --- Mutable resources: id + created_at + updated_at + version ---

class Volunteer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    contact_type: str
    status: str
    required_check_level: str
    restriction_flags: List[str]
    clearance_expires_at: Optional[str]
    total_verified_hours: float
    total_provisional_hours: float
    recognition_points: float
    recognition_tier: str
    prior_status: Optional[str]
    suspension_incident_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict, total=False):
    id: str
    volunteer_id: str
    level: str
    status: str
    findings: Optional[str]
    decided_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Opportunity(TypedDict, total=False):
    id: str
    campus_id: str
    title: str
    description: str
    required_contact_type: str
    restricted_category: str
    capacity: int
    starts_at: str
    ends_at: str
    status: str
    committed_count: int
    projected_count: int
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict, total=False):
    id: str
    opportunity_id: str
    volunteer_id: str
    status: str
    confirmed_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HourEntry(TypedDict, total=False):
    id: str
    placement_id: str
    volunteer_id: str
    worked_date: str
    hours: float
    activity_category: str
    status: str
    points: float
    created_at: str
    updated_at: str
    version: int


class VisitCheckIn(TypedDict, total=False):
    id: str
    campus_id: str
    volunteer_id: str
    placement_id: Optional[str]
    checked_in_at: str
    checked_out_at: Optional[str]
    status: str
    badge_code: str
    close_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    volunteer_id: str
    placement_id: Optional[str]
    severity: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int
