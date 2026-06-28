"""Domain types: entity TypedDicts, status enums, role enum.

All field names are taken verbatim from the PRD. Entities that carry the full
common-field set expose id, created_at, updated_at, and version. The single
exception is FishingLicense, which is immutable after issuance and therefore
exposes only id and created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER = "Customer"
    STORE_ASSOCIATE = "StoreAssociate"
    SERVICE_TECH = "ServiceTech"
    PRICE_ADMIN = "PriceAdmin"


class Sport(str, Enum):
    HOCKEY = "HOCKEY"
    BASEBALL = "BASEBALL"
    FOOTWEAR = "FOOTWEAR"
    FISHING = "FISHING"
    TEAMWEAR = "TEAMWEAR"
    APPAREL = "APPAREL"


class SkuLifecycle(str, Enum):
    STANDARD = "STANDARD"
    SEASONAL = "SEASONAL"
    CLEARANCE = "CLEARANCE"
    DISCONTINUED = "DISCONTINUED"


class FulfillmentType(str, Enum):
    BOPIS = "BOPIS"
    SFS = "SFS"


class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    READY = "READY"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class OrderLineStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class ServiceType(str, Enum):
    SKATE_SHARPEN = "SKATE_SHARPEN"
    RACKET_STRING = "RACKET_STRING"


class ServiceTicketStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_PARTS = "NEEDS_PARTS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class Residency(str, Enum):
    RESIDENT = "RESIDENT"
    NONRESIDENT = "NONRESIDENT"


class FishingLicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class PriceMatchClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MarkdownKind(str, Enum):
    SEASONAL = "SEASONAL"
    CLEARANCE = "CLEARANCE"


class MarkdownStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class TeamOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Sku(TypedDict):
    id: str
    sport: str
    name: str
    size_label: str
    is_footwear: bool
    base_price_cents: int
    requires_license_permit: bool
    embroiderable: bool
    lifecycle: str
    active_markdown_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    name: str
    state_code: str
    ship_from_store_enabled: bool
    pickup_enabled: bool
    created_at: str
    updated_at: str
    version: int


class StoreInventory(TypedDict):
    id: str
    store_id: str
    sku_id: str
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    home_state_code: str
    loyalty_points: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    store_id: str
    fulfillment_type: str
    payment_status: str
    fulfillment_status: str
    provisional_total_cents: int
    final_total_cents: Optional[int]
    loyalty_points_awarded: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    sku_id: str
    store_inventory_id: str
    quantity: int
    unit_price_cents: int
    embroidery_text: Optional[str]
    line_status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict):
    id: str
    customer_id: str
    store_id: str
    service_type: str
    part_sku_id: Optional[str]
    part_store_inventory_id: Optional[str]
    status: str
    service_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class PriceMatchClaim(TypedDict):
    id: str
    order_id: str
    order_line_id: str
    competitor_price_cents: int
    status: str
    approved_unit_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Markdown(TypedDict):
    id: str
    sku_id: str
    markdown_kind: str
    percent_off: int
    effective_from: str
    effective_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TeamOrder(TypedDict):
    id: str
    customer_id: str
    store_id: str
    team_name: str
    status: str
    total_units: int
    spawned_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TeamOrderLine(TypedDict):
    id: str
    team_order_id: str
    sku_id: str
    quantity: int
    embroidery_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Entity TypedDict (common_fields: false -> id/created_at only)
# ---------------------------------------------------------------------------
class FishingLicense(TypedDict):
    id: str
    customer_id: str
    issuing_store_id: str
    residency: str
    valid_from: str
    valid_until: str
    fee_cents: int
    status: str
    created_at: str
