"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    STAFF = "Staff"
    STORE_MANAGER = "StoreManager"


class StaffRoleType(str, Enum):
    FITTER = "FITTER"
    COACH = "COACH"
    BOTH = "BOTH"


class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class SubscriptionTier(str, Enum):
    CLUB_BASIC = "CLUB_BASIC"
    CLUB_PRO = "CLUB_PRO"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ProductCategory(str, Enum):
    SHOE = "SHOE"
    NUTRITION = "NUTRITION"
    GEAR = "GEAR"
    APPAREL = "APPAREL"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    GAIT_ANALYSIS = "GAIT_ANALYSIS"
    SHOE_FITTING = "SHOE_FITTING"
    FOLLOWUP = "FOLLOWUP"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class SessionLevel(str, Enum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PacketStatus(str, Enum):
    RESERVED = "RESERVED"
    ALLOCATED = "ALLOCATED"
    RELEASED = "RELEASED"


class OrderStatus(str, Enum):
    CART = "CART"
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class ShoePairStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REORDER_DUE = "REORDER_DUE"


# ---- Entity TypedDicts (all entities carry common_fields: id/created_at/updated_at/version) ----

class Store(TypedDict):
    id: str
    name: str
    region_code: str
    session_room_count: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    store_id: str
    full_name: str
    role_type: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    loyalty_points: int
    loyalty_tier: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    category: str
    name: str
    price_cents: int
    stock_on_hand: int
    stock_reserved: int
    max_mileage_km: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    member_id: str
    tier: str
    status: str
    monthly_fee_cents: int
    included_fittings_per_month: int
    fittings_used_this_period: int
    started_at: Optional[str]
    current_period_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FittingAppointment(TypedDict):
    id: str
    member_id: str
    fitter_id: str
    service_type: str
    start_at: str
    end_at: str
    status: str
    gait_result: Optional[dict]
    fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict):
    id: str
    coach_id: str
    store_id: str
    level: str
    start_at: str
    end_at: str
    capacity: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionEnrollment(TypedDict):
    id: str
    session_id: str
    member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RaceEvent(TypedDict):
    id: str
    name: str
    event_date: str
    packet_capacity: int
    entry_fee_cents: int
    packets_allocated: int
    active_registrations: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RaceRegistration(TypedDict):
    id: str
    event_id: str
    member_id: str
    payment_status: str
    packet_status: str
    entry_fee_cents: int
    amount_paid_cents: int
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    member_id: str
    status: str
    lines: List[dict]
    subtotal_cents: int
    provisional_discount_cents: Optional[int]
    provisional_total_cents: Optional[int]
    final_discount_cents: Optional[int]
    final_total_cents: Optional[int]
    refund_cents: int
    placed_at: Optional[str]
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShoePair(TypedDict):
    id: str
    member_id: str
    product_id: str
    reminder_threshold_km: int
    total_mileage_km: float
    run_logs: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int
