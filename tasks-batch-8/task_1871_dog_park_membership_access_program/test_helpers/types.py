"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    STEWARD = "Steward"
    PARK_ADMIN = "ParkAdmin"


class MemberStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"


class DogSizeClass(str, Enum):
    SMALL = "SMALL"
    LARGE = "LARGE"


class DogVerificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class GuestPassStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    VOID = "VOID"
    EXPIRED = "EXPIRED"


class AreaClosureStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ParkVisitStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FORCE_CLOSED = "FORCE_CLOSED"


class VisitCloseReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    MEMBER_SUSPENDED = "MEMBER_SUSPENDED"
    NIGHTLY_SWEEP = "NIGHTLY_SWEEP"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class IncidentReportStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class WasteStationStatus(str, Enum):
    OK = "OK"
    NEEDS_SERVICE = "NEEDS_SERVICE"


# All nine resources share the common system-managed fields
# id / created_at / updated_at / version (PRD §2.5).

class Member(TypedDict):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    is_steward: bool
    status: str
    strike_points: int
    provisional_strike_score: int
    guest_passes_used_this_month: int
    created_at: str
    updated_at: str
    version: int


class Dog(TypedDict):
    id: str
    member_id: str
    name: str
    size_class: str
    license_number: str
    vaccination_expires_on: str
    verification_status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    term_start: str
    term_end: str
    charged_fee_cents: int
    renewal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GuestPass(TypedDict):
    id: str
    sponsor_member_id: str
    guest_dog_size_class: str
    valid_on: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PeakWindow(TypedDict):
    start_minute: int
    end_minute: int


class ParkArea(TypedDict):
    id: str
    name: str
    size_class_restriction: str
    capacity: int
    peak_capacity: int
    peak_windows: List[PeakWindow]
    current_occupancy: int
    effective_capacity: int
    created_at: str
    updated_at: str
    version: int


class AreaClosure(TypedDict):
    id: str
    area_id: str
    starts_at: str
    ends_at: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ParkVisit(TypedDict):
    id: str
    member_id: str
    dog_id: Optional[str]
    guest_pass_id: Optional[str]
    area_id: str
    checked_in_at: str
    checked_out_at: Optional[str]
    status: str
    close_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    reporter_member_id: Optional[str]
    subject_member_id: str
    subject_dog_id: Optional[str]
    area_id: Optional[str]
    severity: str
    description: str
    occurred_at: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WasteStation(TypedDict):
    id: str
    area_id: str
    name: str
    fill_pct: int
    status: str
    last_serviced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
