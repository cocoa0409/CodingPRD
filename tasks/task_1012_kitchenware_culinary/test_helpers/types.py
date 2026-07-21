"""Domain types: entity TypedDicts, status enums, and the role enum.

Every persisted resource in this API carries the common server-managed
properties id / created_at / updated_at / version (PRD §2.4), so each
entity TypedDict below lists all four.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Role enum ────────────────────────────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STORE_ASSOCIATE = "StoreAssociate"
    MEMBER = "Member"


# ─── Status / enum vocabularies ───────────────────────────────
class StoreStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SkuCategory(str, Enum):
    COOKWARE = "COOKWARE"
    KNIVES = "KNIVES"
    COFFEE = "COFFEE"
    APPLIANCE = "APPLIANCE"
    TABLETOP = "TABLETOP"


class SkuStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class MemberTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class FulfillmentType(str, Enum):
    BOPIS = "BOPIS"
    SHIP_FROM_STORE = "SHIP_FROM_STORE"
    IN_STORE = "IN_STORE"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    CANCELED = "CANCELED"


class LineStatus(str, Enum):
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    VOID = "VOID"
    RETURNED = "RETURNED"


class ClassStation(str, Enum):
    DEMO_KITCHEN = "DEMO_KITCHEN"
    HEARTH_BAR = "HEARTH_BAR"


class CookingClassStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class ClassRegistrationStatus(str, Enum):
    BOOKED = "BOOKED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELED = "CANCELED"


class ServiceType(str, Enum):
    KNIFE_SHARPENING = "KNIFE_SHARPENING"
    COFFEE_SERVICE = "COFFEE_SERVICE"


class ServiceTicketStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class ReturnReason(str, Enum):
    DEFECTIVE = "DEFECTIVE"
    UNWANTED = "UNWANTED"
    WRONG_ITEM = "WRONG_ITEM"


class RefundDestination(str, Enum):
    ORIGINAL = "ORIGINAL"
    WALLET = "WALLET"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SpecialOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    CANCELED = "CANCELED"


class RegistryEventType(str, Enum):
    WEDDING = "WEDDING"
    HOUSEWARMING = "HOUSEWARMING"
    BIRTHDAY = "BIRTHDAY"


class RegistryStatus(str, Enum):
    ACTIVE = "ACTIVE"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ───
class Store(TypedDict):
    id: str
    name: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Sku(TypedDict):
    id: str
    name: str
    category: str
    list_price_cents: int
    is_bundle: bool
    component_sku_ids: List[str]
    bundle_price_cents: Optional[int]
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    home_store_id: str
    tier: str
    annual_spend_cents: int
    pending_points: int
    earned_points: int
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    line_id: str
    sku_id: str
    qty: int
    unit_price_cents: int
    line_status: str
    is_gift: bool


class Order(TypedDict):
    id: str
    member_id: str
    store_id: str
    fulfillment_type: str
    lines: List[OrderLine]
    payment_status: str
    fulfillment_status: str
    tier_at_pricing: str
    subtotal_cents: int
    tier_discount_cents: int
    tax_cents: int
    total_cents: int
    pending_points: int
    earned_points: int
    refunded_cents: int
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CookingClass(TypedDict):
    id: str
    store_id: str
    title: str
    station: str
    start_at: str
    end_at: str
    capacity: int
    price_cents: int
    registered_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassRegistration(TypedDict):
    id: str
    class_id: str
    member_id: str
    order_id: Optional[str]
    seat_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict):
    id: str
    store_id: str
    member_id: Optional[str]
    service_type: str
    start_at: str
    end_at: str
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict):
    id: str
    order_id: str
    member_id: str
    line_id: str
    return_qty: int
    reason: str
    refund_destination: str
    refund_amount_cents: int
    points_reversed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    member_id: str
    store_id: str
    description: str
    estimated_cost_cents: int
    quoted_total_cents: Optional[int]
    quote_revision: int
    deposit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Registry(TypedDict):
    id: str
    member_id: str
    event_type: str
    event_date: str
    items: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int
