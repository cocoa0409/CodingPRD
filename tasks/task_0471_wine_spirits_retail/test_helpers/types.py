"""Domain types: entity TypedDicts, status enums, role enum (Wine & Spirits Retail API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ──────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    STORE_ASSOCIATE = "StoreAssociate"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ADMIN = "Admin"
    ANONYMOUS = "Anonymous"


# ─── Status enums ───────────────────────────────────────────────────────────
class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"


class VintageStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    ALLOCATION_OPEN = "ALLOCATION_OPEN"
    SOLD_OUT = "SOLD_OUT"
    DELISTED = "DELISTED"


class TaxStatus(str, Enum):
    BONDED = "BONDED"
    TAXED = "TAXED"


class ComplianceStatus(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    BLOCKED = "BLOCKED"


class IdScanStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class OrderFulfillmentStatus(str, Enum):
    CART = "CART"
    SUBMITTED = "SUBMITTED"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReservationState(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    FULFILLED = "FULFILLED"
    RELEASED = "RELEASED"


class ClubTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ClubStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    CONVERTED = "CONVERTED"
    DECLINED = "DECLINED"


class ShipmentStatus(str, Enum):
    LABELED = "LABELED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class Channel(str, Enum):
    POS = "POS"
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"
    SHIP = "SHIP"


class Category(str, Enum):
    WINE = "WINE"
    SPIRITS = "SPIRITS"
    BEER = "BEER"
    GROWLER = "GROWLER"
    KEG = "KEG"


class ContainerType(str, Enum):
    BOTTLE = "BOTTLE"
    CAN = "CAN"
    GROWLER_FILL = "GROWLER_FILL"
    KEG_HALF_BBL = "KEG_HALF_BBL"


class Carrier(str, Enum):
    STORE_COURIER = "STORE_COURIER"
    LICENSED_COMMON_CARRIER = "LICENSED_COMMON_CARRIER"


# ─── Entity TypedDicts ──────────────────────────────────────────────────────
# Versioned entities carry id + created_at + updated_at + version.

class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    container_type: str
    bottle_volume_ml: int
    abv_pct: float
    min_purchase_age: int
    is_allocated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Vintage(TypedDict):
    id: str
    product_id: str
    vintage_year: int
    list_price_cents: int
    allocation_cap_per_customer: Optional[int]
    case_pack_size: int
    status: str
    units_committed: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    vintage_id: str
    tax_status: str
    qty_on_hand: int
    qty_reserved: int
    excise_band_cents_per_unit: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    ship_state_code: str
    age_verified: bool
    compliance_status: str
    lifetime_spend_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    channel: str
    dest_state_code: Optional[str]
    payment_status: str
    fulfillment_status: str
    provisional_total_cents: int
    settled_total_cents: int
    discount_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    vintage_id: str
    qty: int
    lot_id: Optional[str]
    reservation_state: str
    unit_price_cents: int
    line_excise_cents: int
    created_at: str
    updated_at: str
    version: int


class ClubMembership(TypedDict):
    id: str
    customer_id: str
    tier: str
    status: str
    accrued_points: int
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    description: str
    requested_qty: int
    quoted_unit_price_cents: Optional[int]
    customer_counter_price_cents: Optional[int]
    round_count: int
    status: str
    converted_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    carrier: str
    dest_state_code: str
    adult_signature_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StateRule(TypedDict):
    id: str
    state_code: str
    ship_allowed: bool
    growler_keg_allowed: bool
    monthly_volume_limit_ml: Optional[int]
    requires_adult_signature: bool
    created_at: str
    updated_at: str
    version: int


# Append-only audit records: id + created_at only — NO updated_at, NO version.

class IdScan(TypedDict):
    id: str
    customer_id: str
    id_state_code: str
    id_expiry_date: str
    scanned_dob: str
    status: str
    reject_reason: Optional[str]
    created_at: str


class ComplianceWindow(TypedDict):
    id: str
    customer_id: str
    order_id: str
    state_code: str
    volume_ml: int
    window_month: str
    active: bool
    created_at: str
