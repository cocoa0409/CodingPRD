"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource definitions. Entities carrying the standard
system-managed fields (id, created_at, updated_at, version) are modelled with
all four; the three flat catalog resources (PackageCatalog, VehicleSizeRate,
AddOn) carry only id + created_at and therefore omit updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enums ────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CUSTOMER = "Customer"
    DETAILER = "Detailer"
    SCHEDULER = "Scheduler"
    SHOP_MANAGER = "ShopManager"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class VehicleSize(str, Enum):
    SEDAN = "SEDAN"
    SUV = "SUV"
    TRUCK = "TRUCK"
    XL = "XL"


class Tier(str, Enum):
    WASH = "WASH"
    FULL = "FULL"
    CERAMIC = "CERAMIC"


class LocationMode(str, Enum):
    SHOP = "SHOP"
    MOBILE = "MOBILE"


class AddOnCode(str, Enum):
    ENGINE_BAY = "ENGINE_BAY"
    PET_HAIR = "PET_HAIR"
    HEADLIGHT = "HEADLIGHT"


class MembershipStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"
    LAPSED = "LAPSED"


class BayStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class WorkStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    IN_PREP = "IN_PREP"
    IN_SERVICE = "IN_SERVICE"
    CURING = "CURING"
    READY = "READY"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class LineStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PERFORMED = "PERFORMED"
    SKIPPED = "SKIPPED"


class ReworkClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"


# ─── Versioned entities (id + created_at + updated_at + version) ──────

class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    membership_id: Optional[str]
    loyalty_tier: str
    chronological_lifetime_spend_cents: int
    projected_lifetime_spend_cents: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    customer_id: str
    status: str
    monthly_fee_cents: int
    cycle_start_utc: str
    cycle_anchor_day: int
    wash_credit_value_cents: int
    default_vehicle_size: str
    credits_granted_total: int
    credits_consumed_total: int
    credits_expired_total: int
    credits_remaining: int
    created_at: str
    updated_at: str
    version: int


class ServiceBay(TypedDict):
    id: str
    bay_code: str
    status: str
    supports_ceramic: bool
    created_at: str
    updated_at: str
    version: int


class MobileUnit(TypedDict):
    id: str
    unit_code: str
    status: str
    travel_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    customer_id: str
    tier: str
    vehicle_size: str
    location_mode: str
    service_bay_id: Optional[str]
    mobile_unit_id: Optional[str]
    scheduled_start_utc: str
    occupancy_end_utc: str
    vehicle_release_utc: str
    use_membership_credit: bool
    work_status: str
    payment_status: str
    is_member_at_booking: bool
    credit_applied_cents: int
    provisional_total_cents: int
    final_total_cents: int
    amount_charged_cents: int
    amount_refunded_cents: int
    outstanding_balance_cents: int
    spawned_from_rework_claim_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AppointmentAddOn(TypedDict):
    id: str
    appointment_id: str
    addon_code: str
    price_cents_snapshot: int
    extra_minutes_snapshot: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


class JobPhoto(TypedDict):
    id: str
    appointment_id: str
    phase: str
    image_url: str
    created_at: str
    updated_at: str
    version: int


class ReworkClaim(TypedDict):
    id: str
    original_appointment_id: str
    reason: str
    status: str
    rework_appointment_id: Optional[str]
    filed_within_window: bool
    created_at: str
    updated_at: str
    version: int


# ─── Flat catalog resources (id + created_at only — no version) ──────

class PackageCatalog(TypedDict):
    id: str
    tier: str
    base_price_cents: int
    prep_minutes: int
    service_minutes: int
    cure_minutes: int
    guarantee_days: int
    created_at: str


class VehicleSizeRate(TypedDict):
    id: str
    vehicle_size: str
    size_multiplier_bps: int
    created_at: str


class AddOn(TypedDict):
    id: str
    addon_code: str
    price_cents: int
    extra_minutes: int
    created_at: str
