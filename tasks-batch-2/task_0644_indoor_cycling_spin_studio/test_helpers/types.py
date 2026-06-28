"""Domain types: entity TypedDicts, status enums, role enum for the Spin Studio API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    STUDIO_MANAGER = "StudioManager"
    MEMBER = "Member"
    INSTRUCTOR = "Instructor"
    ANONYMOUS = "Anonymous"


# --- Status enums ---
class StudioStatus(str, Enum):
    ACTIVE = "ACTIVE"


class RoomStatus(str, Enum):
    OPEN = "OPEN"


class BikeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class MemberAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CreditPackKind(str, Enum):
    CLASS_PACK = "CLASS_PACK"
    MEMBERSHIP = "MEMBERSHIP"


class CreditPackScope(str, Enum):
    HOME_ONLY = "HOME_ONLY"
    MULTI_STUDIO = "MULTI_STUDIO"


class CreditPackStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    REFUNDED = "REFUNDED"


class AttendanceStatus(str, Enum):
    BOOKED = "BOOKED"
    ATTENDED = "ATTENDED"
    LATE_CANCELLED = "LATE_CANCELLED"
    EARLY_CANCELLED = "EARLY_CANCELLED"
    NO_SHOW = "NO_SHOW"


class BillingStatus(str, Enum):
    CREDIT_HELD = "CREDIT_HELD"
    CREDIT_CONSUMED = "CREDIT_CONSUMED"
    CREDIT_REFUNDED = "CREDIT_REFUNDED"
    FEE_CHARGED = "FEE_CHARGED"


class ShoeStatus(str, Enum):
    NONE = "NONE"
    RESERVED = "RESERVED"
    RETURNED = "RETURNED"
    FORFEITED = "FORFEITED"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    EXPIRED_OFF = "EXPIRED_OFF"
    CANCELLED = "CANCELLED"


class ProductStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISCONTINUED = "DISCONTINUED"


class PenaltyKind(str, Enum):
    LATE_CANCEL = "LATE_CANCEL"
    NO_SHOW = "NO_SHOW"


class RetailOrderStatus(str, Enum):
    PLACED = "PLACED"


# --- Entity TypedDicts (all entities carry id/created_at/updated_at/version) ---
class Studio(TypedDict):
    id: str
    name: str
    city: str
    timezone: str
    late_cancel_window_minutes: int
    late_cancel_fee_cents: int
    no_show_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    studio_id: str
    name: str
    bike_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bike(TypedDict):
    id: str
    room_id: str
    position_row: int
    position_col: int
    label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    email: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    studio_id: str
    room_id: str
    instructor_id: str
    start_utc: str
    end_utc: str
    capacity: int
    waitlist_capacity: int
    booked_count: int
    waitlist_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    home_studio_id: str
    completed_ride_count: int
    active_strike_count: int
    account_status: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class CreditPack(TypedDict):
    id: str
    member_id: str
    kind: str
    purchased_credits: int
    price_cents: int
    consumed_credits: int
    remaining_credits: int
    activated_at: str
    expires_at: str
    scope: str
    grant_studio_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    session_id: str
    member_id: str
    bike_id: str
    credit_pack_id: Optional[str]
    attendance_status: str
    billing_status: str
    first_ride_discount_applied: bool
    shoe_size: Optional[float]
    shoe_fee_cents: int
    shoe_status: str
    booked_at: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    session_id: str
    member_id: str
    credit_pack_id: str
    enqueued_at: str
    status: str
    promoted_reservation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    studio_id: str
    sku: str
    name: str
    unit_price_cents: int
    stock_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetailOrder(TypedDict):
    id: str
    member_id: str
    studio_id: str
    product_id: str
    quantity: int
    pay_from_wallet: bool
    subtotal_cents: int
    wallet_applied_cents: int
    card_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PenaltyCharge(TypedDict):
    id: str
    member_id: str
    reservation_id: str
    kind: str
    amount_cents: int
    counts_as_strike: bool
    waived: bool
    charged_at: str
    created_at: str
    updated_at: str
    version: int
