"""Domain types: entity TypedDicts, status enums, role enum for the Trophy, Awards & Engraving API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ────────────────────────────────────────────
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    SHOP_STAFF = "ShopStaff"
    SHOP_MANAGER = "ShopManager"


# ─── Status enums ─────────────────────────────────────
class ProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class ProofStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    ENGRAVING = "ENGRAVING"
    ASSEMBLED = "ASSEMBLED"


class AllocStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class FulfillmentStatus(str, Enum):
    STAGED = "STAGED"
    HANDED_OFF = "HANDED_OFF"


class ProductType(str, Enum):
    TROPHY = "TROPHY"
    PLAQUE = "PLAQUE"
    MEDAL = "MEDAL"
    ACRYLIC = "ACRYLIC"
    CRYSTAL = "CRYSTAL"


class ServiceLevel(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"
    RUSH = "RUSH"


class RushTier(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"
    RUSH = "RUSH"


class PromoKind(str, Enum):
    PERCENT = "PERCENT"
    FLAT = "FLAT"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    FULL = "FULL"


class ProofKind(str, Enum):
    TEXT = "TEXT"
    LOGO = "LOGO"


class FulfillmentMethod(str, Enum):
    PICKUP = "PICKUP"
    SHIP = "SHIP"


# ─── Entity TypedDicts ────────────────────────────────
# common_fields: true — carry id + created_at + updated_at + version
class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    org_name: Optional[str]
    lifetime_completed_orders: int
    on_time_rate_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CatalogProduct(TypedDict, total=False):
    id: str
    sku: str
    name: str
    product_type: str
    base_price_cents: int
    engraving_price_per_char_cents: int
    logo_setup_fee_cents: int
    standard_lead_days: int
    bom: list
    active: bool
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict, total=False):
    id: str
    code: str
    name: str
    on_hand_qty: int
    allocated_qty: int
    available_qty: int
    reorder_point: int
    low_stock: bool
    created_at: str
    updated_at: str
    version: int


class RushPolicy(TypedDict, total=False):
    id: str
    name: str
    standard_surcharge_pct: float
    expedited_surcharge_pct: float
    rush_surcharge_pct: float
    rush_min_business_days: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class PromoCode(TypedDict, total=False):
    id: str
    code: str
    kind: str
    percent_off: Optional[float]
    flat_off_cents: Optional[int]
    min_subtotal_cents: int
    max_uses: Optional[int]
    uses_count: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    promo_code_id: Optional[str]
    reorder_source_order_id: Optional[str]
    service_level: str
    due_date: str
    production_status: str
    payment_status: str
    rush_tier: Optional[str]
    estimate_subtotal_cents: int
    estimate_total_cents: int
    invoice_subtotal_cents: Optional[int]
    invoice_total_cents: Optional[int]
    deposit_due_cents: Optional[int]
    amount_paid_cents: int
    line_count: int
    ready_at: Optional[str]
    fulfilled_at: Optional[str]
    due_date_met: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    catalog_product_id: str
    quantity: int
    engraving_text: str
    include_logo: bool
    line_status: str
    assembled_count: int
    char_count: int
    line_subtotal_cents: int
    volume_tier: Optional[str]
    volume_discount_cents: int
    created_at: str
    updated_at: str
    version: int


class Proof(TypedDict, total=False):
    id: str
    order_line_id: str
    proof_kind: str
    content_ref: str
    proof_status: str
    revision_round: int
    approved_text_snapshot: Optional[str]
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComponentAllocation(TypedDict, total=False):
    id: str
    order_line_id: str
    component_id: str
    qty: int
    alloc_status: str
    created_at: str
    updated_at: str
    version: int


class Fulfillment(TypedDict, total=False):
    id: str
    order_id: str
    method: str
    ship_address: Optional[str]
    ship_fee_cents: int
    ship_weight_grams: int
    fulfillment_status: str
    handed_off_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — Payment carries ONLY id + created_at (no updated_at, no version)
class Payment(TypedDict, total=False):
    id: str
    order_id: str
    amount_cents: int
    kind: str
    pay_status: str
    created_at: str
