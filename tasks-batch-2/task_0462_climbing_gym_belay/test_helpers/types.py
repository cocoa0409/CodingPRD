"""Domain types: entity TypedDicts, status enums, role enum.

All fields and statuses follow the Climbing Gym Belay API PRD exactly.
Two resources (Waiver, Enrollment) carry ONLY id + created_at — no
updated_at, no version — per PRD section 2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    MEMBER = "Member"
    FRONT_DESK = "FrontDesk"
    EXAMINER = "Examiner"
    ROUTE_SETTER = "RouteSetter"
    GYM_ADMIN = "GymAdmin"


# ─── Status enums ─────────────────────────────────────────────────────────
class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class WaiverStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class MembershipBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class MembershipAccessStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    YOUTH_TEAM = "YOUTH_TEAM"


class CertificationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class Discipline(str, Enum):
    BELAY = "BELAY"
    LEAD = "LEAD"


class RouteStatus(str, Enum):
    OPEN = "OPEN"
    STRIPPED = "STRIPPED"


class RouteStyle(str, Enum):
    SLAB = "SLAB"
    OVERHANG = "OVERHANG"
    ROOF = "ROOF"


class CheckInStatus(str, Enum):
    ON_FLOOR = "ON_FLOOR"
    CHECKED_OUT = "CHECKED_OUT"


class EntryKind(str, Enum):
    MEMBERSHIP = "MEMBERSHIP"
    DAY_PASS = "DAY_PASS"


class ClinicStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


class ItemKind(str, Enum):
    HARNESS = "HARNESS"
    SHOES = "SHOES"
    ROPE = "ROPE"


class RentalStatus(str, Enum):
    OUT = "OUT"
    RETURNED = "RETURNED"
    LOST = "LOST"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# common_fields: true → id + created_at + updated_at + version
class Member(TypedDict):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    is_youth: bool
    wallet_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → ONLY id + created_at (no updated_at, no version)
class Waiver(TypedDict):
    id: str
    member_id: str
    signed_at: str
    expires_at: str
    minor_guardian_name: Optional[str]
    status: str
    created_at: str


class Membership(TypedDict):
    id: str
    member_id: str
    plan_tier: str
    monthly_fee_cents: int
    cycle_start: str
    cycle_end: str
    billing_status: str
    access_status: str
    past_due_since: Optional[str]
    frozen_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    member_id: str
    discipline: str
    status: str
    weighted_score: Optional[float]
    min_station_score: Optional[int]
    passed_at: Optional[str]
    expires_at: Optional[str]
    examiner_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    name: str
    floor_capacity: int
    occupancy: int
    requires_belay_cert: bool
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    facility_id: str
    setter_user_id: str
    grade: int
    style: str
    difficulty_points: int
    status: str
    set_on: str
    created_at: str
    updated_at: str
    version: int


class CheckIn(TypedDict):
    id: str
    member_id: str
    facility_id: str
    entry_kind: str
    gear_bundle: bool
    price_cents: int
    status: str
    checked_in_at: str
    checked_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Clinic(TypedDict):
    id: str
    title: str
    starts_at: str
    ends_at: str
    seat_capacity: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → ONLY id + created_at (no updated_at, no version)
class Enrollment(TypedDict):
    id: str
    clinic_id: str
    member_id: str
    status: str
    created_at: str


class Rental(TypedDict):
    id: str
    member_id: str
    item_kind: str
    deposit_cents: int
    rented_at: str
    due_at: str
    returned_at: Optional[str]
    late_fee_cents: int
    refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    member_id: str
    facility_id: str
    certification_id: Optional[str]
    severity: str
    description: str
    status: str
    reported_at: str
    created_at: str
    updated_at: str
    version: int
