"""Domain types: entity TypedDicts, status enums, role enum.

All field names are PRD-exact. Every entity carries the full common-field set
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    INVENTORY_MANAGER = "InventoryManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CORPORATE_BUYER = "CorporateBuyer"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status enums ---
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    WON_BACK = "WON_BACK"


class ChurnBand(str, Enum):
    OK = "OK"
    AT_RISK = "AT_RISK"
    CHURN_IMMINENT = "CHURN_IMMINENT"


class SkuStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    LABEL_HOLD = "LABEL_HOLD"
    DISCONTINUED = "DISCONTINUED"


class LotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    RECALLED = "RECALLED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class SubscriptionTier(str, Enum):
    STARTER = "STARTER"
    CLASSIC = "CLASSIC"
    RESERVE = "RESERVE"


class OrderKind(str, Enum):
    ONE_TIME = "ONE_TIME"
    SUBSCRIPTION = "SUBSCRIPTION"
    GIFT = "GIFT"
    CORPORATE_BULK = "CORPORATE_BULK"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class BulkQuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    REWARDED = "REWARDED"
    VOID = "VOID"


class WinbackOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class Zone(str, Enum):
    Z1 = "Z1"
    Z2 = "Z2"
    Z3 = "Z3"
    Z4 = "Z4"


class Category(str, Enum):
    HOT_SAUCE = "HOT_SAUCE"
    COFFEE = "COFFEE"
    SNACK = "SNACK"


class StorageClass(str, Enum):
    AMBIENT = "AMBIENT"
    PERISHABLE = "PERISHABLE"


# --- Entity TypedDicts (all common_fields: true) ---
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    home_zone: str
    status: str
    wallet_credit_cents: int
    loyalty_points_balance: int
    lifetime_order_count: int
    lifetime_failed_payment_count: int
    lifetime_skip_count: int
    last_order_at: Optional[str]
    churn_risk_score: int
    churn_band: str
    winback_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Sku(TypedDict):
    id: str
    name: str
    category: str
    storage_class: str
    unit_price_cents: int
    allergens: List[str]
    status: str
    label_approved: bool
    available_units: int
    reserved_units: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    sku_id: str
    lot_code: str
    produced_units: int
    remaining_units: int
    expiry_iso: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    sku_id: str
    tier: str
    cadence_days: int
    status: str
    next_renewal_iso: str
    consecutive_skip_count: int
    provisional_charge_cents: int
    pending_swap_sku_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    subscription_id: Optional[str]
    order_kind: str
    ship_zone: str
    gift_recipient_email: Optional[str]
    gift_box_count: int
    requested_redeem_points: int
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    discount_cents: int
    handling_cents: int
    shipping_cents: int
    redeemed_points: int
    total_cents: int
    accrued_points: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    sku_id: str
    lot_id: Optional[str]
    quantity: int
    unit_price_cents: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


class BulkQuote(TypedDict):
    id: str
    corporate_buyer_id: str
    sku_id: str
    quantity: int
    gift_box_count: int
    status: str
    line_subtotal_cents: int
    discount_cents: int
    handling_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    referrer_id: str
    referred_id: str
    status: str
    reward_points: int
    created_at: str
    updated_at: str
    version: int


class WinbackOffer(TypedDict):
    id: str
    customer_id: str
    discount_pct: float
    expires_iso: str
    status: str
    created_at: str
    updated_at: str
    version: int
