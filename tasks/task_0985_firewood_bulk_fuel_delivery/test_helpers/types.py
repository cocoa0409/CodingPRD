"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    CUSTOMER_SERVICE = "CustomerService"
    OPERATIONS_MANAGER = "OperationsManager"
    ROUTE_PLANNER = "RoutePlanner"
    DRIVER = "Driver"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ProductKind(str, Enum):
    CORD = "CORD"
    HALF_CORD = "HALF_CORD"
    PELLET_TON = "PELLET_TON"
    PELLET_BAG = "PELLET_BAG"


class Species(str, Enum):
    OAK = "OAK"
    MAPLE = "MAPLE"
    BIRCH = "BIRCH"
    MIXED_HARDWOOD = "MIXED_HARDWOOD"
    HARDWOOD_BLEND = "HARDWOOD_BLEND"
    SOFTWOOD_BLEND = "SOFTWOOD_BLEND"


class SeasonedGrade(str, Enum):
    GREEN = "GREEN"
    SEMI_SEASONED = "SEMI_SEASONED"
    KILN_DRIED = "KILN_DRIED"


class SubscriptionTier(str, Enum):
    HEARTH = "HEARTH"
    HEARTH_PLUS = "HEARTH_PLUS"
    ESTATE = "ESTATE"


class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    SHORTFALL = "SHORTFALL"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    PAYMENT_FAILED = "PAYMENT_FAILED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PAYMENT = "PENDING_PAYMENT"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class PaymentEventKind(str, Enum):
    AUTHORIZE = "AUTHORIZE"
    CAPTURE = "CAPTURE"
    REFUND = "REFUND"
    CHARGEBACK = "CHARGEBACK"
    ADJUST_CREDIT = "ADJUST_CREDIT"


class VolumeTier(str, Enum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# MoistureReading and PaymentEvent are append-only: only id + created_at (PRD §2.4).

class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    street_address: str
    postal_code: str
    credit_balance_cents: int
    outstanding_refund_cents: int
    lifetime_cord_equivalent_delivered: float
    loyalty_tier: str
    account_status: str
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    product_kind: str
    species: str
    seasoned_grade: str
    base_price_cents: int
    moisture_ceiling_pct: float
    available_qty: float
    reserved_qty: float
    discontinued: bool
    created_at: str
    updated_at: str
    version: int


class AreaRestriction(TypedDict, total=False):
    id: str
    name: str
    postal_codes: List[str]
    restricted_kinds: List[str]
    restricted_species: List[str]
    enforcement_window_start: str
    enforcement_window_end: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    customer_id: str
    tier: str
    season_year: int
    commitment_cord_equivalent: float
    delivered_cord_equivalent: float
    prepaid_cents: int
    discount_pct: float
    stacking_included: bool
    status: str
    activated_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict, total=False):
    id: str
    route_code: str
    depot_name: str
    service_postal_prefixes: List[str]
    capacity_cord_equivalent: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class DeliveryWindow(TypedDict, total=False):
    id: str
    route_id: str
    service_date: str
    start_hour: int
    end_hour: int
    capacity_cord_equivalent: float
    committed_cord_equivalent: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    subscription_id: Optional[str]
    delivery_window_id: Optional[str]
    delivery_street_address: str
    delivery_postal_code: str
    requested_delivery_date: str
    payment_status: str
    fulfillment_status: str
    stacking_addon: bool
    stacking_fee_cents: int
    subtotal_cents: int
    volume_discount_cents: int
    subscription_discount_cents: int
    loyalty_discount_cents: int
    seasonal_surcharge_cents: int
    delivery_fee_cents: int
    total_cents: int
    total_cord_equivalent: float
    scheduled_at: Optional[str]
    delivered_at: Optional[str]
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    quantity: float
    unit_price_cents: int
    cord_equivalent_per_unit: float
    line_cord_equivalent: float
    volume_tier_applied: str
    extended_price_cents: int
    moisture_reading_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MoistureReading(TypedDict, total=False):
    # Append-only: only id + created_at are system-managed (PRD §2.4).
    id: str
    order_line_id: str
    recorded_by_user_id: str
    moisture_pct: float
    reading_pass: bool
    recorded_at: str
    created_at: str


class Invoice(TypedDict, total=False):
    id: str
    order_id: str
    invoice_number: str
    amount_cents: int
    paid_cents: int
    refunded_cents: int
    status: str
    due_date: str
    issued_at: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentEvent(TypedDict, total=False):
    # Append-only: only id + created_at are system-managed (PRD §2.4).
    id: str
    invoice_id: str
    event_kind: str
    amount_cents: int
    external_ref: str
    created_at: str
