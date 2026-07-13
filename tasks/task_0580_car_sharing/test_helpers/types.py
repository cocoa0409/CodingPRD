"""Domain types: entity TypedDicts, status enums, role enum.

Field shapes follow the Car Sharing PRD §2.4 (common resource properties) and
§3 (workflows). Entities carrying id/created_at/updated_at/version list all four;
the ProtectionPlan carries only id + created_at (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------- Roles
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    HOST = "Host"
    GUEST = "Guest"
    PLATFORM_ADMIN = "PlatformAdmin"


# ------------------------------------------------------------------- Statuses
class HostStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class GuestVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class VehicleStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    SNOOZED = "SNOOZED"
    UNLISTED = "UNLISTED"


class AvailabilityBlockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class BlockType(str, Enum):
    BOOKED = "BOOKED"
    HOST_BLOCKED = "HOST_BLOCKED"
    MAINTENANCE = "MAINTENANCE"


class PricingRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class TripStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DECLINED = "DECLINED"


class InspectionPhase(str, Enum):
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class Claimant(str, Enum):
    HOST = "HOST"
    GUEST = "GUEST"


class ExtensionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ProtectionTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class PayoutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PAID = "PAID"
    FAILED = "FAILED"


# ------------------------------------------------------------------- Entities
class Host(TypedDict):
    id: str
    name: str
    email: str
    payout_method_ref: Optional[str]
    status: str
    pending_balance_cents: int
    available_balance_cents: int
    reserved_payout_cents: int
    lifetime_earnings_cents: int
    lifetime_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    name: str
    email: str
    verification_status: str
    license_number: Optional[str]
    license_state: Optional[str]
    license_expiry_date: Optional[str]
    driver_risk_score: int
    outstanding_balance_cents: int
    at_fault_claim_count: int
    late_return_count: int
    completed_trip_count: int
    created_at: str
    updated_at: str
    version: int


class ProtectionPlan(TypedDict):
    # PRD §2.4: immutable config — carries ONLY id + created_at (no updated_at / version).
    id: str
    tier: str
    deductible_cents: int
    daily_premium_cents: int
    coverage_limit_cents: int
    host_earnings_pct: float
    active: bool
    created_at: str


class Vehicle(TypedDict):
    id: str
    host_id: str
    make: str
    model: str
    year: int
    base_daily_price_cents: int
    location_city: str
    daily_mileage_limit: int
    weekly_discount_pct: float
    monthly_discount_pct: float
    odometer_current: int
    status: str
    booked_night_count: int
    completed_trip_count: int
    created_at: str
    updated_at: str
    version: int


class AvailabilityBlock(TypedDict):
    id: str
    vehicle_id: str
    trip_id: Optional[str]
    block_type: str
    start_date: str
    end_date: str
    nights: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PricingRule(TypedDict):
    id: str
    vehicle_id: str
    start_date: str
    end_date: str
    daily_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    vehicle_id: str
    guest_id: str
    protection_plan_id: str
    start_date: str
    end_date: str
    nights: int
    status: str
    discounted_subtotal_cents: int
    protection_premium_cents: int
    estimated_total_cents: int
    estimated_host_earnings_cents: int
    deductible_snapshot_cents: int
    checkin_odometer: Optional[int]
    checkin_fuel_pct: Optional[int]
    checkout_odometer: Optional[int]
    checkout_fuel_pct: Optional[int]
    scheduled_return_at: str
    actual_return_at: Optional[str]
    mileage_fee_cents: int
    fuel_fee_cents: int
    late_days: int
    late_fee_cents: int
    final_total_cents: Optional[int]
    final_host_earnings_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InspectionReport(TypedDict):
    id: str
    trip_id: str
    phase: str
    odometer_reading: int
    fuel_level_pct: int
    photo_refs: List[str]
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    trip_id: str
    claimant: str
    damage_amount_cents: int
    description: str
    status: str
    covered_amount_cents: Optional[int]
    guest_deductible_cents: Optional[int]
    host_recovery_cents: Optional[int]
    uncovered_cents: Optional[int]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Extension(TypedDict):
    id: str
    trip_id: str
    new_end_date: str
    previous_end_date: str
    added_nights: int
    status: str
    added_earnings_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    host_id: str
    trip_id: Optional[str]
    amount_cents: int
    status: str
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
