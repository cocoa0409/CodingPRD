"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values are taken verbatim from the PRD contract.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    STUDIO_MANAGER = "StudioManager"
    MEMBER = "Member"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class StudioStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ClassTemplateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PackagePlanKind(str, Enum):
    INTRO = "INTRO"
    CREDIT_PACK = "CREDIT_PACK"
    MEMBERSHIP = "MEMBERSHIP"


class PackagePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MemberStanding(str, Enum):
    GOOD = "GOOD"
    RESTRICTED = "RESTRICTED"


class MembershipStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class WalletEntryKind(str, Enum):
    GRANT = "GRANT"
    RESERVE_DEBIT = "RESERVE_DEBIT"
    CANCEL_REFUND = "CANCEL_REFUND"
    EXPIRY_FORFEIT = "EXPIRY_FORFEIT"
    ROLLOVER_FORFEIT = "ROLLOVER_FORFEIT"


class ClassSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    FULL = "FULL"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ReservationBookingStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class ReservationAttendanceStatus(str, Enum):
    PENDING = "PENDING"
    CHECKED_IN = "CHECKED_IN"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    LATE_CANCELLED = "LATE_CANCELLED"


class FeeChargeKind(str, Enum):
    LATE_CANCEL = "LATE_CANCEL"
    NO_SHOW = "NO_SHOW"


class FeeChargeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    WAIVED = "WAIVED"


# --------------------------------------------------------------------------
# Entity TypedDicts — entities carrying the full common-field quartet
# (id, created_at, updated_at, version)
# --------------------------------------------------------------------------
class Studio(TypedDict):
    id: str
    name: str
    state_code: str
    timezone: str
    status: str
    active_room_count: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    studio_id: str
    name: str
    physical_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    home_studio_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassTemplate(TypedDict):
    id: str
    name: str
    duration_min: int
    credit_cost: int
    late_cancel_window_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackagePlan(TypedDict):
    id: str
    name: str
    kind: str
    price_cents: int
    grant_credits: int
    validity_days: int
    rollover_cap: int
    freeze_max_days: int
    intro_once_per_member: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    home_studio_id: str
    has_used_intro: bool
    no_show_strikes: int
    standing: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    plan_id: str
    status: str
    credit_balance: int
    activated_at: Optional[str]
    cycle_start: Optional[str]
    expires_at: Optional[str]
    frozen_at: Optional[str]
    freeze_days_used: int
    rolled_over_credits: int
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    studio_id: str
    room_id: str
    instructor_id: str
    template_id: str
    starts_at: str
    ends_at: str
    seat_capacity: int
    waitlist_capacity: int
    status: str
    booked_count: int
    waitlisted_count: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    session_id: str
    member_id: str
    membership_id: str
    booking_status: str
    attendance_status: str
    credits_charged: int
    waitlist_position: int
    late_fee_cents: int
    promoted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeCharge(TypedDict):
    id: str
    member_id: str
    reservation_id: str
    kind: str
    amount_cents: int
    status: str
    credit_refunded: bool
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only ledger entity (common_fields: false) — id + created_at only.
# A WalletEntry has NO updated_at and NO version.
# --------------------------------------------------------------------------
class WalletEntry(TypedDict):
    id: str
    membership_id: str
    reservation_id: Optional[str]
    kind: str
    delta: int
    note: str
    created_at: str
