"""Domain types: entity TypedDicts, status enums, role enum.

All types describe the Wind Tunnel API resources exactly as the PRD specifies
them. Every top-level resource carries id/created_at/updated_at/version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum (PRD §2.1 — exactly four roles, spelled precisely)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    FLYER = "Flyer"
    INSTRUCTOR = "Instructor"
    FRONT_DESK = "FrontDesk"
    MANAGER = "Manager"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class TunnelStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    MAINTENANCE = "MAINTENANCE"


class InstructorTier(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFF = "OFF"


class ExperienceStatus(str, Enum):
    FIRST_TIME = "FIRST_TIME"
    RETURNING = "RETURNING"


class MembershipTier(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    PRO = "PRO"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class BookingType(str, Enum):
    WALK_IN = "WALK_IN"
    RESERVATION = "RESERVATION"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class SessionOpStatus(str, Enum):
    OPEN = "OPEN"
    RUNNING = "RUNNING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SessionStaffingStatus(str, Enum):
    UNSTAFFED = "UNSTAFFED"
    STAFFED = "STAFFED"


class FlightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    FLOWN = "FLOWN"
    ABORTED = "ABORTED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class WaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"


class CoachingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Entity TypedDicts (all common_fields: id, created_at, updated_at, version)
# --------------------------------------------------------------------------
class Tunnel(TypedDict):
    id: str
    name: str
    max_weight_kg: float
    default_capacity: int
    turnaround_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    name: str
    cert_level: str
    tier: str
    sessions_completed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    name: str
    weight_kg: float
    experience_status: str
    health_flags: List[str]
    membership_tier: str
    reflight_credit_minutes: int
    total_credits_minted: int
    total_credits_consumed: int
    wallet_cents: int
    confirmed_booking_count: int
    outstanding_addon_cents: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    tier: str
    discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PackageProduct(TypedDict):
    id: str
    name: str
    included_minutes: int
    base_price_cents: int
    min_experience: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    member_id: str
    package_id: str
    booking_type: str
    party_size: int
    lead_days: int
    minutes_included: int
    minutes_remaining: int
    total_price_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    tunnel_id: str
    instructor_id: Optional[str]
    start_utc: str
    end_utc: str
    capacity: int
    op_status: str
    staffing_status: str
    seats_taken: int
    seats_available: int
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict):
    id: str
    booking_id: str
    session_id: str
    member_id: str
    scheduled_minutes: int
    status: str
    minutes_charged: int
    flown_minutes: int
    reflight_credit_granted: int
    video_addon_purchased: bool
    video_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    member_id: str
    weight_kg_declared: float
    health_ok: bool
    signed_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CoachingBooking(TypedDict):
    id: str
    flight_id: str
    instructor_id: str
    minutes: int
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
