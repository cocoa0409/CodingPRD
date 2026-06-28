"""Domain types: entity TypedDicts, status enums, role enum for the Blow-Dry Bar API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────────

class AppointmentLifecycleStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AppointmentSettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class EventBlockStatus(str, Enum):
    HOLD = "HOLD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RetailSaleStatus(str, Enum):
    SOLD = "SOLD"
    VOIDED = "VOIDED"


class PackagePurchaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REFUNDED = "REFUNDED"


class AddOnCategory(str, Enum):
    UPDO = "UPDO"
    BRAID = "BRAID"
    EXTENSION = "EXTENSION"


class MembershipTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    VIP = "VIP"


class CommissionTier(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    MASTER = "MASTER"


class BlockType(str, Enum):
    GROUP = "GROUP"
    BRIDAL = "BRIDAL"


class PaymentMethod(str, Enum):
    CREDIT = "CREDIT"
    PREPAY = "PREPAY"


class ArrivalStatus(str, Enum):
    ON_TIME = "ON_TIME"
    LATE = "LATE"
    NO_SHOW = "NO_SHOW"


class UserRole(str, Enum):
    FRONT_DESK = "FrontDesk"
    FINANCE_MANAGER = "FinanceManager"
    STYLIST = "Stylist"
    MEMBER = "Member"


# ─── Entity TypedDicts (all primary resources carry common fields) ────────────

class StyleService(TypedDict):
    id: str
    name: str
    base_duration_minutes: int
    base_price_cents: int
    blowout_credit_cost: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    name: str
    category: str
    extra_duration_minutes: int
    price_cents: int
    discount_eligible: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class MembershipPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    included_blowout_credits: int
    member_discount_pct: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    membership_plan_id: Optional[str]
    blowout_credit_balance: int
    prepay_balance_cents: int
    no_show_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Stylist(TypedDict):
    id: str
    full_name: str
    commission_tier: str
    shift_start_minute: int
    shift_end_minute: int
    earned_commission_cents: int
    earned_tips_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Chair(TypedDict):
    id: str
    label: str
    open_minute: int
    close_minute: int
    turnover_buffer_minutes: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    member_id: str
    chair_id: str
    stylist_id: str
    style_service_id: str
    event_block_id: Optional[str]
    start_minute: int
    scheduled_duration_minutes: int
    end_minute: int
    payment_method: str
    list_amount_cents: int
    discount_cents: int
    service_charge_cents: int
    credits_applied: int
    tip_cents: int
    tip_pool_cents: int
    stylist_tip_cents: int
    commission_amount_cents: int
    house_amount_cents: int
    arrival_status: str
    late_minutes: int
    lifecycle_status: str
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class AppointmentAddOn(TypedDict):
    id: str
    appointment_id: str
    add_on_id: str
    captured_price_cents: int
    captured_duration_minutes: int
    discount_applied_cents: int
    created_at: str
    updated_at: str
    version: int


class EventBlock(TypedDict):
    id: str
    organizer_member_id: str
    block_type: str
    window_start_minute: int
    window_end_minute: int
    reserved_chair_ids: List[str]
    party_size: int
    deposit_cents: int
    deposit_paid_cents: int
    gratuity_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    unit_price_cents: int
    stock_qty: int
    retail_commission_pct: float
    created_at: str
    updated_at: str
    version: int


class RetailSale(TypedDict):
    id: str
    product_id: str
    member_id: str
    attributed_stylist_id: Optional[str]
    quantity: int
    gross_cents: int
    retail_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackagePurchase(TypedDict):
    id: str
    member_id: str
    credits_purchased: int
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
