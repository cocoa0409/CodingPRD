"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model. Entities that carry no version/updated_at
(LicenseType) omit those fields; every other entity carries the full common set.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ProductCategory(str, Enum):
    TACKLE = "TACKLE"
    ROD = "ROD"
    REEL = "REEL"
    LINE = "LINE"
    LIVE_BAIT = "LIVE_BAIT"
    MISC = "MISC"


class LicenseClass(str, Enum):
    RESIDENT = "RESIDENT"
    NONRESIDENT = "NONRESIDENT"


class LicenseSaleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class GuideStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUSPENDED = "SUSPENDED"


class CharterStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    WAITLISTED = "WAITLISTED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class TournamentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class EntryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    WEIGHED = "WEIGHED"
    WINNER = "WINNER"
    WITHDRAWN = "WITHDRAWN"


class ServiceType(str, Enum):
    REEL_REPAIR = "REEL_REPAIR"
    ROD_REPAIR = "ROD_REPAIR"
    SPOOLING = "SPOOLING"


class ServiceOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    DIAGNOSED = "DIAGNOSED"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    SHOP_CLERK = "ShopClerk"
    GUIDE = "Guide"
    SHOP_MANAGER = "ShopManager"


# ─── Entity TypedDicts ─────────────────────────────────────────
# common_fields: true → id + created_at + updated_at + version
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    residency_state: str
    loyalty_points_balance: int
    lifetime_points_earned: int
    loyalty_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_price_cents: int
    stock_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → only id + created_at (no version / updated_at)
class LicenseType(TypedDict):
    id: str
    code: str
    state_code: str
    license_class: str
    base_price_cents: int
    youth_max_age: Optional[int]
    youth_price_cents: Optional[int]
    senior_min_age: Optional[int]
    senior_price_cents: Optional[int]
    peak_surcharge_cents: int
    peak_start_month: Optional[int]
    peak_end_month: Optional[int]
    min_age: int
    season_start_date: str
    season_end_date: str
    validity_days: int
    created_at: str


class LicenseSale(TypedDict):
    id: str
    customer_id: str
    license_type_id: str
    issued_at: str
    valid_from: str
    valid_until: str
    price_paid_cents: int
    points_earned: int
    refund_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Guide(TypedDict):
    id: str
    name: str
    license_no: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Charter(TypedDict):
    id: str
    guide_id: str
    title: str
    start_at: str
    end_at: str
    capacity: int
    booked_seats: int
    price_per_seat_cents: int
    fuel_surcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CharterBooking(TypedDict):
    id: str
    charter_id: str
    customer_id: str
    seats: int
    waitlist_requested: bool
    booking_status: str
    payment_status: str
    provisional_total_cents: int
    final_total_cents: Optional[int]
    amount_paid_cents: int
    refund_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Tournament(TypedDict):
    id: str
    name: str
    species: str
    start_at: str
    end_at: str
    entry_fee_cents: int
    min_qualifying_weight_grams: int
    prize_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TournamentEntry(TypedDict):
    id: str
    tournament_id: str
    customer_id: str
    status: str
    weigh_ins: List[dict]
    best_weight_grams: int
    final_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    customer_id: str
    product_id: Optional[str]
    service_type: str
    base_service_cents: int
    line_price_cents_per_meter: int
    estimated_line_meters: int
    actual_line_meters: int
    line_units: int
    parts_cents: int
    quoted_cents: Optional[int]
    final_subtotal_cents: Optional[int]
    grand_total_cents: Optional[int]
    points_earned: int
    stock_consumed: bool
    status: str
    created_at: str
    updated_at: str
    version: int
