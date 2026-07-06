"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CREATOR = "Creator"
    PLATFORM_ADMIN = "PlatformAdmin"
    FULFILLMENT_PARTNER = "FulfillmentPartner"


# --- Status enums ---

class CreatorVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class StorefrontIntegrationChannel(str, Enum):
    NATIVE = "NATIVE"
    ETSY = "ETSY"
    SHOPIFY = "SHOPIFY"


class StorefrontIntegrationStatus(str, Enum):
    NONE = "NONE"
    LINKED = "LINKED"
    SUSPENDED = "SUSPENDED"


class ProductCategory(str, Enum):
    APPAREL = "APPAREL"
    DRINKWARE = "DRINKWARE"
    ACCESSORY = "ACCESSORY"
    PRINT = "PRINT"


class DesignStatus(str, Enum):
    UPLOADED = "UPLOADED"
    MOCKUP_READY = "MOCKUP_READY"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class OrderPaymentStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUND_PARTIAL = "REFUND_PARTIAL"
    REFUND_FULL = "REFUND_FULL"
    VOIDED = "VOIDED"


class OrderFulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    ROUTED = "ROUTED"
    IN_PRINT = "IN_PRINT"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class FulfillmentJobStatus(str, Enum):
    QUEUED = "QUEUED"
    PRINTING = "PRINTING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    REPRINT_REQUESTED = "REPRINT_REQUESTED"
    CANCELLED = "CANCELLED"


class FulfillmentPartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ReprintFaultCategory(str, Enum):
    PARTNER_FAULT = "PARTNER_FAULT"
    CONSUMER_FAULT = "CONSUMER_FAULT"
    PLATFORM_GESTURE = "PLATFORM_GESTURE"


class ReprintRequestStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PayoutCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    RETURNED = "RETURNED"


class ChannelSyncChannel(str, Enum):
    ETSY = "ETSY"
    SHOPIFY = "SHOPIFY"


class ChannelSyncEventType(str, Enum):
    LISTING_MIRROR = "LISTING_MIRROR"
    ORDER_INGEST = "ORDER_INGEST"
    SYNC_FAIL = "SYNC_FAIL"


# --- Entity TypedDicts ---
# common_fields: true entities carry id, created_at, updated_at, version.
# ChannelSyncEvent has common_fields: false — id + created_at only.


class Creator(TypedDict):
    id: str
    email: str
    display_name: str
    payout_country_code: str
    payout_wallet_cents: int
    verification_status: str
    default_payout_fee_bps: int
    reprint_strike_count: int
    created_at: str
    updated_at: str
    version: int


class Storefront(TypedDict):
    id: str
    creator_id: str
    slug: str
    integration_channel: str
    integration_status: str
    markup_bps: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    category: str
    base_cost_cents: int
    dimensions_json: dict
    created_at: str
    updated_at: str
    version: int


class Variant(TypedDict):
    id: str
    product_id: str
    color: str
    size: str
    base_cost_delta_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Design(TypedDict):
    id: str
    creator_id: str
    file_hash: str
    status: str
    mockup_url: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    storefront_id: str
    design_id: str
    variant_id: str
    title: str
    listed_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FulfillmentPartner(TypedDict):
    id: str
    name: str
    country_code: str
    cost_multiplier_bps: int
    current_backlog_hours: int
    max_backlog_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    storefront_id: str
    buyer_email: str
    ship_country_code: str
    item_count: int
    listing_id: str
    is_sample: bool
    gross_amount_cents: int
    shipping_cents: int
    payment_status: str
    fulfillment_status: str
    routed_partner_id: Optional[str]
    creator_net_cents: int
    created_at: str
    updated_at: str
    version: int


class FulfillmentJob(TypedDict):
    id: str
    order_id: str
    partner_id: str
    status: str
    reprint_generation: int
    partner_charge_cents: int
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReprintRequest(TypedDict):
    id: str
    job_id: str
    fault_category: str
    reason_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoutCycle(TypedDict):
    id: str
    creator_id: str
    cycle_start: str
    cycle_end: str
    gross_earnings_cents: int
    fee_cents: int
    net_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only log; carries only id + created_at
class ChannelSyncEvent(TypedDict):
    id: str
    storefront_id: str
    channel: str
    event_type: str
    external_ref: str
    created_at: str
