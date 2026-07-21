"""Domain types: entity TypedDicts, status enums, and the role enum.

All entities in this API carry the common server-managed fields
(id, created_at, updated_at, version), so every TypedDict below includes them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum value sets ─────────────────────────────────────────────

class MembershipTier(str, Enum):
    BASIC = "BASIC"
    PREMIER = "PREMIER"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class GearCategory(str, Enum):
    TENT = "TENT"
    BACKPACK = "BACKPACK"
    KAYAK = "KAYAK"
    STOVE = "STOVE"
    APPAREL = "APPAREL"


class GearUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED_OUT = "RENTED_OUT"


class ConditionGrade(str, Enum):
    NEW = "NEW"
    GOOD = "GOOD"
    FAIR = "FAIR"


class RentalStatus(str, Enum):
    QUOTED = "QUOTED"
    PICKED_UP = "PICKED_UP"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    UNFULFILLED = "UNFULFILLED"
    FULFILLED = "FULFILLED"
    RETURNED = "RETURNED"


class TradeInStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    REJECTED = "REJECTED"


class DescribedCondition(str, Enum):
    LIKE_NEW = "LIKE_NEW"
    GOOD = "GOOD"
    WORN = "WORN"


class PayoutMethod(str, Enum):
    INSTANT_CREDIT = "INSTANT_CREDIT"
    CONSIGNMENT = "CONSIGNMENT"


class ClassTripCategory(str, Enum):
    CLASS = "CLASS"
    GUIDED_TRIP = "GUIDED_TRIP"


class ClassTripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    WAITLISTED = "WAITLISTED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PermitPassStatus(str, Enum):
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"


class UserRole(str, Enum):
    MEMBER = "Member"
    STORE_STAFF = "StoreStaff"
    PUBLIC = "Public"


# ─── Entity TypedDicts ────────────────────────────────────────────────────

class Member(TypedDict):
    id: str
    email: str
    full_name: str
    membership_tier: str
    membership_status: str
    store_credit_cents: int
    loyalty_points_balance: int
    lifetime_eligible_spend_cents: int
    created_at: str
    updated_at: str
    version: int


class GearSku(TypedDict):
    id: str
    name: str
    category: str
    retail_price_cents: int
    rentable: bool
    daily_rental_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class GearUnit(TypedDict):
    id: str
    gear_sku_id: str
    serial_number: str
    condition_grade: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict):
    id: str
    member_id: str
    gear_unit_id: str
    start_at: str
    due_at: str
    returned_at: Optional[str]
    status: str
    daily_rate_cents: int
    rental_days: int
    damage_waiver: bool
    deposit_cents: int
    estimated_charge_cents: int
    final_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    member_id: str
    lines: list
    use_store_credit: bool
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    loyalty_points_earned: int
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    member_id: str
    gear_sku_id: str
    described_condition: str
    payout_method: str
    status: str
    appraised_value_cents: Optional[int]
    member_counter_cents: Optional[int]
    instant_credit_cents: Optional[int]
    consignment_estimate_cents: Optional[int]
    resale_price_cents: Optional[int]
    payout_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ClassTrip(TypedDict):
    id: str
    title: str
    category: str
    start_at: str
    end_at: str
    capacity: int
    price_cents: int
    status: str
    seats_reserved: int
    seats_available: int
    waitlist_count: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    member_id: str
    class_trip_id: str
    status: str
    price_paid_cents: int
    booked_from_waitlist: bool
    created_at: str
    updated_at: str
    version: int


class PermitAllocation(TypedDict):
    id: str
    park_name: str
    season_start: str
    season_end: str
    total_quota: int
    price_cents: int
    issued_count: int
    available_quota: int
    created_at: str
    updated_at: str
    version: int


class PermitPass(TypedDict):
    id: str
    member_id: str
    permit_allocation_id: str
    entry_date: str
    status: str
    price_cents: int
    created_at: str
    updated_at: str
    version: int
