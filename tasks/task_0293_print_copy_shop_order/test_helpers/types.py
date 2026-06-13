"""Domain types: entity TypedDicts, status enums, role enum for the Print & Copy Shop Order API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    SHOP_STAFF = "ShopStaff"
    PRODUCTION_OPERATOR = "ProductionOperator"
    CUSTOMER = "Customer"


# ─── Status enums ─────────────────────────────────────────────────────────
class ProductCategory(str, Enum):
    COPIES = "COPIES"
    BANNER = "BANNER"
    BINDING = "BINDING"


class OrderProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    INVOICED = "INVOICED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    PREFLIGHT_OK = "PREFLIGHT_OK"
    PROOF_PENDING = "PROOF_PENDING"
    PROOF_APPROVED = "PROOF_APPROVED"
    PRICE_LOCKED = "PRICE_LOCKED"
    PRODUCED = "PRODUCED"


class PreflightStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ProofStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class FulfillmentMethod(str, Enum):
    PICKUP = "PICKUP"
    SHIP = "SHIP"


class FulfillmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HANDED_OFF = "HANDED_OFF"


class PressBookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class CapacityReservationStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class LoyaltyTier(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class SurchargeKind(str, Enum):
    PER_UNIT = "PER_UNIT"
    FLAT = "FLAT"


# ─── Entity TypedDicts (all common_fields: true → id+created_at+updated_at+version) ──
class Shop(TypedDict):
    id: str
    name: str
    tax_rate_bps: int
    rush_surcharge_bps: int
    rush_cutoff_hour_utc: int
    standard_turnaround_days: int
    rush_turnaround_days: int
    daily_unit_capacity: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    shop_id: str
    name: str
    category: str
    base_unit_price_cents: int
    unit_size: int
    requires_proof: bool
    requires_press: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class PricingTier(TypedDict):
    id: str
    product_id: str
    min_quantity: int
    discount_bps: int
    created_at: str
    updated_at: str
    version: int


class FinishingOption(TypedDict):
    id: str
    product_id: str
    code: str
    surcharge_kind: str
    surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    name: str
    shop_id: str
    completed_order_count: int
    lifetime_paid_cents: int
    loyalty_score: float
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    shop_id: str
    customer_id: str
    reordered_from_order_id: Optional[str]
    production_status: str
    payment_status: str
    subtotal_cents: int
    loyalty_discount_cents: int
    rush_fee_cents: int
    tax_cents: int
    total_cents: int
    promised_ready_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    quantity: int
    finishing_codes: List[str]
    service_level: str
    status: str
    production_units: int
    estimate_line_cents: int
    final_line_cents: Optional[int]
    rush_surcharge_cents: int
    promised_ready_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Artwork(TypedDict):
    id: str
    order_line_id: str
    file_name: str
    page_count: int
    dpi: int
    bleed_mm: float
    preflight_status: str
    preflight_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Proof(TypedDict):
    id: str
    order_line_id: str
    round_number: int
    status: str
    change_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Fulfillment(TypedDict):
    id: str
    order_id: str
    method: str
    ship_address: Optional[str]
    ship_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Press(TypedDict):
    id: str
    shop_id: str
    name: str
    cleanup_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class PressBooking(TypedDict):
    id: str
    press_id: str
    order_line_id: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityReservation(TypedDict):
    id: str
    shop_id: str
    order_line_id: str
    production_date: str
    units: int
    status: str
    created_at: str
    updated_at: str
    version: int
