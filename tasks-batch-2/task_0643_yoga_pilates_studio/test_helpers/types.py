"""Domain types: entity TypedDicts, status enums, role enum.

Reflects the resource shapes described in the Yoga & Pilates Studio PRD §2.4 and §3.
Every primary resource carries id/created_at/updated_at/version, EXCEPT FeeCharge which
carries only id and created_at (PRD §2.4: "A FeeCharge has no updated_at and no version field").
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---- Role enum ----
class UserRole(str, Enum):
    STUDIO_MANAGER = "StudioManager"
    MEMBER = "Member"
    INSTRUCTOR = "Instructor"


# ---- Status enums ----
class MemberAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RoomStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RoomType(str, Enum):
    REFORMER = "REFORMER"
    MAT = "MAT"


class TeacherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class IntroOfferStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class Discipline(str, Enum):
    VINYASA = "VINYASA"
    YIN = "YIN"
    REFORMER = "REFORMER"
    MAT_PILATES = "MAT_PILATES"


class ClassSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    FULL = "FULL"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EntitlementKind(str, Enum):
    MEMBERSHIP = "MEMBERSHIP"
    CLASS_PACK = "CLASS_PACK"
    INTRO = "INTRO"


class EntitlementLifecycleStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class EntitlementFreezeStatus(str, Enum):
    UNFROZEN = "UNFROZEN"
    FROZEN = "FROZEN"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    WAITLISTED = "WAITLISTED"
    CHECKED_IN = "CHECKED_IN"
    ATTENDED = "ATTENDED"
    CANCELLED_EARLY = "CANCELLED_EARLY"
    CANCELLED_LATE = "CANCELLED_LATE"
    NO_SHOW = "NO_SHOW"


class FeeType(str, Enum):
    LATE_CANCEL = "LATE_CANCEL"
    NO_SHOW = "NO_SHOW"


class FeeChargeStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    WAIVED = "WAIVED"


class WorkshopKind(str, Enum):
    WORKSHOP = "WORKSHOP"
    TEACHER_TRAINING = "TEACHER_TRAINING"


class WorkshopStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    APPLIED = "APPLIED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED_BY_STUDIO = "CANCELLED_BY_STUDIO"


# ---- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ----
class Member(TypedDict):
    id: str
    email: str
    full_name: str
    home_studio_state: str
    is_new_student: bool
    lifetime_attended_count: int
    no_show_strike_count: int
    account_status: str
    outstanding_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    name: str
    room_type: str
    station_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Teacher(TypedDict):
    id: str
    full_name: str
    certifications: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IntroOffer(TypedDict):
    id: str
    name: str
    price_cents: int
    credits_total: int
    window_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    room_id: str
    teacher_id: str
    recurrence_parent_id: Optional[str]
    discipline: str
    start_utc: str
    end_utc: str
    published_capacity: int
    waitlist_capacity: int
    status: str
    booked_count: int
    waitlisted_count: int
    created_at: str
    updated_at: str
    version: int


class Entitlement(TypedDict):
    id: str
    member_id: str
    kind: str
    intro_offer_id: Optional[str]
    price_cents: int
    credits_total: int
    credits_used: int
    credits_remaining: int
    cycle_start_utc: str
    cycle_end_utc: str
    auto_renew: bool
    rollover_cap: int
    lifecycle_status: str
    freeze_status: str
    frozen_at_utc: Optional[str]
    frozen_days_consumed: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    member_id: str
    class_session_id: str
    entitlement_id: str
    status: str
    waitlist_position: Optional[int]
    credit_charged: bool
    booked_at_utc: str
    created_at: str
    updated_at: str
    version: int


class Workshop(TypedDict):
    id: str
    room_id: str
    lead_teacher_id: str
    title: str
    kind: str
    start_utc: str
    end_utc: str
    seat_capacity: int
    deposit_cents: int
    price_cents: int
    status: str
    confirmed_seat_count: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    member_id: str
    workshop_id: str
    status: str
    deposit_paid_cents: int
    balance_due_cents: int
    created_at: str
    updated_at: str
    version: int


# ---- FeeCharge: immutable shape, carries ONLY id + created_at (PRD §2.4) ----
class FeeCharge(TypedDict):
    id: str
    member_id: str
    reservation_id: str
    fee_type: str
    amount_cents: int
    status: str
    created_at: str
