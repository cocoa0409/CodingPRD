"""Domain types: entity TypedDicts, status enums, role enum (Travel Agency Tour Booking API)."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ────────────────────────────────────────────────────────
class TourPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class BookingStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"


class BookingComponentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"


class MilestoneKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"


class MilestoneStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    WALLET = "WALLET"
    BANK_TRANSFER = "BANK_TRANSFER"


class PaymentState(str, Enum):
    APPLIED = "APPLIED"
    REFUNDED = "REFUNDED"


class CoverageTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class InsuranceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class PenaltyTier(str, Enum):
    TIER_FREE = "TIER_FREE"
    TIER_LOW = "TIER_LOW"
    TIER_HIGH = "TIER_HIGH"
    TIER_FULL = "TIER_FULL"


class RefundDestination(str, Enum):
    WALLET = "WALLET"
    ORIGINAL = "ORIGINAL"


class SupplierKind(str, Enum):
    FLIGHT = "FLIGHT"
    HOTEL = "HOTEL"
    ACTIVITY = "ACTIVITY"


class ComponentKind(str, Enum):
    FLIGHT = "FLIGHT"
    HOTEL = "HOTEL"
    ACTIVITY = "ACTIVITY"


class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    TRAVEL_AGENT = "TravelAgent"
    CUSTOMER = "Customer"
    SUPPLIER = "Supplier"


# ─── Entity TypedDicts (all entities carry common_fields: true) ──────────
class Agency(TypedDict):
    id: str
    name: str
    currency: str
    now_utc: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    agency_id: str
    email: str
    full_name: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    agency_id: str
    name: str
    kind: str
    auto_confirm: bool
    created_at: str
    updated_at: str
    version: int


class TourPackage(TypedDict):
    id: str
    agency_id: str
    title: str
    base_price_per_person_cents: int
    deposit_pct: int
    balance_due_days_before_departure: int
    min_group_size_for_discount: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    agency_id: str
    customer_id: str
    tour_package_id: str
    departure_date: str
    traveler_count: int
    subtotal_cents: int
    insurance_premium_cents: int
    grand_total_cents: int
    paid_cents: int
    status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class Traveler(TypedDict):
    id: str
    booking_id: str
    full_name: str
    is_lead: bool
    passport_no: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BookingComponent(TypedDict):
    id: str
    booking_id: str
    supplier_id: str
    kind: str
    starts_at: str
    ends_at: str
    is_mandatory: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentMilestone(TypedDict):
    id: str
    booking_id: str
    kind: str
    amount_due_cents: int
    due_date: str
    settled_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    booking_id: str
    milestone_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    booking_id: str
    coverage_tier: str
    premium_cents: int
    refundable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CancellationRecord(TypedDict):
    id: str
    booking_id: str
    cancelled_at: str
    penalty_tier: str
    penalty_pct: int
    refundable_base_cents: int
    penalty_cents: int
    refund_cents: int
    refund_destination: str
    created_at: str
    updated_at: str
    version: int
