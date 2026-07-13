"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API carries the full managed-field set (id, created_at,
updated_at, version), so every TypedDict lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---
class UserRole(str, Enum):
    RINK_MANAGER = "RinkManager"
    FRONT_DESK = "FrontDesk"
    SKATER = "Skater"


# --- Status enums ---
class IceSlotStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AdmissionStatus(str, Enum):
    ADMITTED = "ADMITTED"
    EXITED = "EXITED"
    REFUNDED = "REFUNDED"


class ClassStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class LeagueStatus(str, Enum):
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    IN_SEASON = "IN_SEASON"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class LockerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SharpeningStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    PICKED_UP = "PICKED_UP"


class Membership(str, Enum):
    MEMBER = "MEMBER"
    NON_MEMBER = "NON_MEMBER"


class SlotPurpose(str, Enum):
    PUBLIC_SKATE = "PUBLIC_SKATE"
    LEARN_TO_SKATE = "LEARN_TO_SKATE"
    LEAGUE = "LEAGUE"
    RENTAL = "RENTAL"
    BROOMBALL = "BROOMBALL"
    PARTY = "PARTY"


class BookingType(str, Enum):
    PRIVATE_RENTAL = "PRIVATE_RENTAL"
    BROOMBALL = "BROOMBALL"
    PARTY = "PARTY"


# --- Entity shapes (all carry id/created_at/updated_at/version) ---
class Rink(TypedDict):
    id: str
    name: str
    resurface_buffer_minutes: int
    open_hour_utc: int
    close_hour_utc: int
    peak_start_hour_utc: int
    public_skate_capacity: int
    public_skate_fee_cents: int
    rental_skate_count: int
    locker_count: int
    locker_fee_cents: int
    available_rental_skates: int
    available_lockers: int
    created_at: str
    updated_at: str
    version: int


class Skater(TypedDict):
    id: str
    full_name: str
    email: str
    membership: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class IceSlot(TypedDict):
    id: str
    rink_id: str
    purpose: str
    start_utc: str
    end_utc: str
    status: str
    admitted_count: int
    available_capacity: int
    created_at: str
    updated_at: str
    version: int


class PublicSkateAdmission(TypedDict):
    id: str
    ice_slot_id: str
    skater_id: str
    rental_skate: bool
    captured_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LearnToSkateClass(TypedDict):
    id: str
    ice_slot_id: str
    prerequisite_class_id: Optional[str]
    level_name: str
    capacity: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    class_id: str
    skater_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TuitionSubscription(TypedDict):
    id: str
    enrollment_id: str
    monthly_fee_cents: int
    proration_mode: str
    billing_cycle_start: str
    billing_cycle_end: str
    total_sessions_in_cycle: int
    sessions_attended: int
    captured_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class League(TypedDict):
    id: str
    name: str
    sport: str
    season_start: str
    season_end: str
    roster_capacity: int
    roster_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeagueRegistration(TypedDict):
    id: str
    league_id: str
    skater_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LockerAssignment(TypedDict):
    id: str
    rink_id: str
    skater_id: str
    league_registration_id: Optional[str]
    locker_number: int
    season_start_date: str
    season_end_date: str
    size: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SlotBooking(TypedDict):
    id: str
    ice_slot_id: str
    skater_id: str
    booking_type: str
    includes_resurface: bool
    base_fee_cents: int
    per_guest_cents: int
    guest_count_booked: int
    guest_count_final: int
    tax_rate: float
    quoted_cents: int
    final_cents: int
    captured_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SharpeningOrder(TypedDict):
    id: str
    skater_id: str
    skate_type: str
    price_cents: int
    queue_position: int
    status: str
    created_at: str
    updated_at: str
    version: int
