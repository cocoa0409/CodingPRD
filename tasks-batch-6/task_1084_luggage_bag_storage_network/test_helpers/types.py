"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    TRAVELER = "Traveler"
    HOST = "Host"
    PLATFORM_ADMIN = "PlatformAdmin"


class HostStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TravelerStatus(str, Enum):
    ACTIVE = "ACTIVE"


class InsuranceTier(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class LocationStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    STORED = "STORED"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BagStatus(str, Enum):
    AWAITING_DROP = "AWAITING_DROP"
    SEALED = "SEALED"
    RETRIEVED = "RETRIEVED"
    VOIDED = "VOIDED"


class ExtensionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class ClaimReason(str, Enum):
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"
    THEFT = "THEFT"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    REVERSED = "REVERSED"


# --- Entity TypedDicts (all entities carry id/created_at/updated_at/version) ---

class Host(TypedDict):
    id: str
    display_name: str
    email: str
    platform_fee_bps: int
    max_concurrent_bookings: int
    status: str
    pending_payout_cents: int
    payout_balance_cents: int
    lifetime_earnings_cents: int
    rating_sum: int
    rating_count: int
    avg_rating: float
    created_at: str
    updated_at: str
    version: int


class Traveler(TypedDict):
    id: str
    email: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePlan(TypedDict):
    id: str
    tier: str
    per_bag_coverage_cents: int
    premium_cents_per_bag_day: int
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    host_id: str
    name: str
    address: str
    daily_bag_capacity: int
    oversize_capacity: int
    per_bag_day_rate_cents: int
    oversize_surcharge_cents_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    location_id: str
    traveler_id: str
    insurance_plan_id: str
    check_in_date: str
    check_out_date: str
    bag_count: int
    oversize_count: int
    billable_days: int
    estimated_total_cents: int
    final_total_cents: Optional[int]
    overage_days: int
    late_fee_cents: int
    dropoff_at: Optional[str]
    pickup_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bag(TypedDict):
    id: str
    booking_id: str
    declared_value_cents: int
    dimension_sum_cm: int
    is_oversize: bool
    seal_code: Optional[str]
    drop_photo_url: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Extension(TypedDict):
    id: str
    booking_id: str
    previous_check_out_date: str
    new_check_out_date: str
    added_days: int
    added_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    booking_id: str
    bag_id: str
    reason: str
    description: str
    claimed_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    host_id: str
    booking_id: str
    gross_cents: int
    platform_fee_cents: int
    claim_deduction_cents: int
    net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Rating(TypedDict):
    id: str
    booking_id: str
    score: int
    comment: Optional[str]
    created_at: str
    updated_at: str
    version: int
