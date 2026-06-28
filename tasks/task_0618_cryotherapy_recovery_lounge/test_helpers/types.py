"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model and state machines.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LOCATION_MANAGER = "LocationManager"
    MEMBER = "Member"
    TECHNICIAN = "Technician"


# ─── Status enums ─────────────────────────────────────────────────────────
class LocationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"


class TechnicianShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"


class WaiverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CANCELLED = "CANCELLED"


class CreditPackStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class InvoiceKind(str, Enum):
    SIGNUP = "SIGNUP"
    RENEWAL = "RENEWAL"
    UPGRADE_PRORATION = "UPGRADE_PRORATION"
    FREEZE_FEE = "FREEZE_FEE"


class InvoiceStatus(str, Enum):
    PAID = "PAID"


class ServiceCode(str, Enum):
    WHOLE_BODY_CRYO = "WHOLE_BODY_CRYO"
    RED_LIGHT = "RED_LIGHT"
    COMPRESSION = "COMPRESSION"
    INFRARED_SAUNA = "INFRARED_SAUNA"


class MembershipTier(str, Enum):
    BASE = "BASE"
    PLUS = "PLUS"
    ELITE = "ELITE"


class CreditSource(str, Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    PACK = "PACK"
    SPLIT = "SPLIT"


# ─── Entities with full common_fields (id, created_at, updated_at, version) ──
class Location(TypedDict):
    id: str
    name: str
    state_code: str
    timezone: str
    status: str
    open_booking_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceType(TypedDict):
    id: str
    code: str
    name: str
    duration_minutes: int
    buffer_minutes: int
    credit_cost: int
    requires_medical_clearance: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    location_id: str
    service_type_id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    location_id: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TechnicianShift(TypedDict):
    id: str
    technician_id: str
    location_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MembershipPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    monthly_credit_grant: int
    rollover_cap: int
    late_cancel_fee_waived: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    home_location_id: str
    email: str
    full_name: str
    state_code: str
    contraindication_flag: bool
    intro_offer_used: bool
    credit_balance: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    member_id: str
    screening_answers: Dict[str, Any]
    has_contraindication: bool
    signed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    member_id: str
    plan_id: str
    status: str
    cycle_anchor_at: str
    current_cycle_end_at: str
    granted_credits_remaining: int
    freeze_cycles_remaining: int
    lifetime_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class CreditPack(TypedDict):
    id: str
    member_id: str
    is_intro: bool
    total_credits: int
    remaining_credits: int
    price_paid_cents: int
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    member_id: str
    location_id: str
    room_id: str
    service_type_id: str
    starts_at: str
    occupies_until_at: str
    credits_charged: int
    credit_source: str
    fee_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity: id + created_at ONLY (no updated_at, no version) ────
class Invoice(TypedDict):
    id: str
    created_at: str
    subscription_id: str
    kind: str
    amount_cents: int
    status: str
