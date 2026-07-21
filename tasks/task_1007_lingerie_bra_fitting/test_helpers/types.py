"""Domain types: entity TypedDicts, status enums, and the role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role ─────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    FITTER = "Fitter"
    STORE_MANAGER = "StoreManager"
    BILLING_CLERK = "BillingClerk"


# ─── Status enums ─────────────────────────────────────────────────────────
class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class OrderLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    FULFILLED = "FULFILLED"
    EXCHANGED = "EXCHANGED"


class StockStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class ExchangeStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REIMBURSED = "REIMBURSED"


class ClaimDecision(str, Enum):
    PENDING = "PENDING"
    APPROVE = "APPROVE"
    DENY = "DENY"


class ReminderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    DISMISSED = "DISMISSED"
    CANCELLED = "CANCELLED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


# ─── Value enums ──────────────────────────────────────────────────────────
class FittingType(str, Enum):
    STANDARD = "STANDARD"
    POST_SURGICAL = "POST_SURGICAL"
    MASTECTOMY = "MASTECTOMY"


class FitPreference(str, Enum):
    SNUG = "SNUG"
    STANDARD = "STANDARD"
    RELAXED = "RELAXED"


class ProductCategory(str, Enum):
    EVERYDAY_BRA = "EVERYDAY_BRA"
    SPORTS_BRA = "SPORTS_BRA"
    MASTECTOMY_BRA = "MASTECTOMY_BRA"
    LINGERIE_SET = "LINGERIE_SET"


class HygieneClass(str, Enum):
    STANDARD_RETURNABLE = "STANDARD_RETURNABLE"
    INTIMATE_NON_RETURNABLE = "INTIMATE_NON_RETURNABLE"


class OrderType(str, Enum):
    STANDARD = "STANDARD"
    SPECIAL_ORDER = "SPECIAL_ORDER"
    GIFT = "GIFT"


class ItemCondition(str, Enum):
    SEALED = "SEALED"
    TRIED_ON = "TRIED_ON"
    WORN = "WORN"


class LoyaltyReason(str, Enum):
    ORDER_EARN = "ORDER_EARN"
    ORDER_REVERSAL = "ORDER_REVERSAL"
    FINAL_ADJUSTMENT = "FINAL_ADJUSTMENT"
    EXCHANGE_REVERSAL = "EXCHANGE_REVERSAL"
    PROMOTION = "PROMOTION"
    CORRECTION = "CORRECTION"


# ─── Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ───
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    post_mastectomy_flag: bool
    loyalty_points: int
    loyalty_tier: str
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Fitter(TypedDict):
    id: str
    full_name: str
    post_surgical_certified: bool
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class FittingRoom(TypedDict):
    id: str
    room_name: str
    capacity: int
    is_private: bool
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class FittingAppointment(TypedDict):
    id: str
    customer_id: str
    fitter_id: str
    room_id: str
    fitting_type: str
    scheduled_start: str
    duration_minutes: int
    scheduled_end: str
    underbust_cm: Optional[float]
    bust_cm: Optional[float]
    fit_preference: str
    recommended_band: Optional[int]
    recommended_cup: Optional[str]
    recommended_size: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    style_name: str
    brand: str
    category: str
    base_price_cents: int
    hygiene_class: str
    is_mastectomy: bool
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class SKU(TypedDict):
    id: str
    product_id: str
    band_size: int
    cup_size: str
    sku_code: str
    price_cents: int
    stock_on_hand: int
    reserved_count: int
    available_units: int
    is_active: bool
    stock_status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    order_type: str
    is_gift: bool
    gift_message: Optional[str]
    gift_recipient_name: Optional[str]
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    discount_cents: int
    gift_wrap_fee_cents: int
    special_order_fee_cents: int
    total_cents: int
    provisional_points: int
    final_points: int
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    sku_id: str
    quantity: int
    unit_price_cents: int
    line_gross_cents: int
    line_discount_cents: int
    line_net_cents: int
    is_special_order: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Exchange(TypedDict):
    id: str
    order_id: str
    order_line_id: str
    item_condition: str
    reason: Optional[str]
    store_credit_issued_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict):
    id: str
    order_id: str
    claim_amount_cents: int
    adjudicated_amount_cents: Optional[int]
    decision: str
    covered_amount_cents: int
    reimbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplacementReminder(TypedDict):
    id: str
    customer_id: str
    order_line_id: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger row: id + created_at only (no updated_at/version)
class LoyaltyEvent(TypedDict):
    id: str
    customer_id: str
    points_delta: int
    reason: str
    order_id: Optional[str]
    created_at: str
