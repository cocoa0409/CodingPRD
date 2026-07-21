"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    GUIDE = "Guide"
    STORE_STAFF = "StoreStaff"
    COOP_ADMIN = "CoopAdmin"


class MembershipTier(str, Enum):
    BASIC = "BASIC"
    PREMIER = "PREMIER"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CLOSED = "CLOSED"


class ProductCategory(str, Enum):
    TENT = "TENT"
    SLEEPING = "SLEEPING"
    COOKING = "COOKING"
    APPAREL = "APPAREL"
    CLIMBING = "CLIMBING"
    PADDLE = "PADDLE"


class RentalUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED_OUT = "RENTED_OUT"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RentalUnitCondition(str, Enum):
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    PICKED_UP = "PICKED_UP"
    RETURNED = "RETURNED"
    DAMAGE_ASSESSED = "DAMAGE_ASSESSED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TripStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    DEPARTED = "DEPARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Certification(str, Enum):
    NONE = "NONE"
    SWIFTWATER = "SWIFTWATER"
    ALPINE = "ALPINE"
    WILDERNESS_FIRST_AID = "WILDERNESS_FIRST_AID"


class GuideStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TripBookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TradeInStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class PayoutType(str, Enum):
    CASH = "CASH"
    CREDIT = "CREDIT"


class RepairStage(str, Enum):
    RECEIVED = "RECEIVED"
    DIAGNOSED = "DIAGNOSED"
    IN_REPAIR = "IN_REPAIR"
    READY = "READY"
    PICKED_UP = "PICKED_UP"


class BillingStage(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class WarrantyStatus(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    COVERED = "COVERED"
    DENIED = "DENIED"


class PassType(str, Enum):
    DAY = "DAY"
    SEASON = "SEASON"
    ANNUAL = "ANNUAL"


class CoverageStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PurchaseStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"


class DeclarationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class LedgerReason(str, Enum):
    PURCHASE_EARN = "PURCHASE_EARN"
    PURCHASE_REDEEM = "PURCHASE_REDEEM"
    BOOKING_REDEEM = "BOOKING_REDEEM"
    BOOKING_REFUND = "BOOKING_REFUND"
    PURCHASE_REFUND_REVERSAL = "PURCHASE_REFUND_REVERSAL"


# ---- common_fields: true entities carry id + created_at + updated_at + version ----

class Member(TypedDict):
    id: str
    email: str
    full_name: str
    membership_tier: str
    membership_status: str
    join_fee_cents: int
    loyalty_points_balance: int
    eligible_spend_cents: int
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    retail_price_cents: int
    tax_rate: float
    replacement_value_cents: int
    is_rentable: bool
    base_daily_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class RentalUnit(TypedDict):
    id: str
    product_id: str
    asset_tag: str
    status: str
    condition: str
    created_at: str
    updated_at: str
    version: int


class RentalReservation(TypedDict):
    id: str
    member_id: str
    rental_unit_id: str
    product_id: str
    start_date: str
    end_date: str
    rental_days: int
    status: str
    rental_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    title: str
    guide_id: Optional[str]
    start_time: str
    end_time: str
    capacity: int
    seats_confirmed: int
    price_cents: int
    required_certification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Guide(TypedDict):
    id: str
    full_name: str
    certifications: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TripBooking(TypedDict):
    id: str
    trip_id: str
    member_id: str
    price_paid_cents: int
    points_redeemed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    member_id: str
    product_id: str
    condition_grade: str
    status: str
    offered_cash_cents: int
    offered_credit_cents: int
    counter_ask_cents: Optional[int]
    rounds: int
    accepted_payout_type: Optional[str]
    accepted_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    member_id: str
    product_id: str
    rental_unit_id: Optional[str]
    purchase_date: str
    repair_stage: str
    billing_stage: str
    warranty_status: str
    labor_cents: int
    parts_cents: int
    billed_cents: int
    created_at: str
    updated_at: str
    version: int


class Pass(TypedDict):
    id: str
    member_id: str
    pass_type: str
    valid_from: str
    valid_to: str
    price_cents: int
    coverage_status: str
    voided: bool
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    member_id: str
    product_id: str
    quantity: int
    status: str
    quoted_price_cents: Optional[int]
    deposit_cents: int
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict):
    id: str
    member_id: str
    line_items: list
    points_redeemed: int
    subtotal_cents: int
    tax_cents: int
    loyalty_redemption_cents: int
    total_cents: int
    loyalty_points_earned: int
    eligible_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DividendDeclaration(TypedDict):
    id: str
    year: int
    declared_rate: float
    status: str
    total_payout_cents: int
    payouts: list
    created_at: str
    updated_at: str
    version: int


# ---- common_fields: false entity (append-only): id + created_at only ----

class LoyaltyLedger(TypedDict):
    id: str
    member_id: str
    delta: int
    reason: str
    ref_id: Optional[str]
    created_at: str
