"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the common fields id, created_at, updated_at,
and version (PRD Section 2.4). No append-only entities exist here.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    BENCH_TECH = "BenchTech"
    SALES_ASSOCIATE = "SalesAssociate"
    CUSTOMER = "Customer"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ProductCategory(str, Enum):
    DECK = "DECK"
    TRUCKS = "TRUCKS"
    WHEELS = "WHEELS"
    GRIP = "GRIP"
    WAX = "WAX"
    COMPLETE = "COMPLETE"
    SURFBOARD = "SURFBOARD"
    WETSUIT = "WETSUIT"
    ACCESSORY = "ACCESSORY"


class CustomerTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class CoachDiscipline(str, Enum):
    SURF = "SURF"
    SKATE = "SKATE"


class RentalAssetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OUT = "OUT"


class RentalAssetCondition(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    NEEDS_SERVICE = "NEEDS_SERVICE"


class LessonStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class RentalFulfillmentStatus(str, Enum):
    RESERVED = "RESERVED"
    PICKED_UP = "PICKED_UP"
    RETURNED = "RETURNED"
    RELEASED = "RELEASED"


class RentalPaymentStatus(str, Enum):
    DEPOSIT_HELD = "DEPOSIT_HELD"
    DEPOSIT_CAPTURED = "DEPOSIT_CAPTURED"
    DEPOSIT_REFUNDED = "DEPOSIT_REFUNDED"


class BoardBuildStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceTicketStatus(str, Enum):
    INTAKE = "INTAKE"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class TradeInMode(str, Enum):
    TRADE_IN = "TRADE_IN"
    CONSIGNMENT = "CONSIGNMENT"


class TradeInPayoutChoice(str, Enum):
    CASH = "CASH"
    STORE_CREDIT = "STORE_CREDIT"


class TradeInStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPRAISED = "APPRAISED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    LISTED = "LISTED"
    SOLD = "SOLD"


class SpecialOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CUSTOMER_REVIEW = "CUSTOMER_REVIEW"
    APPROVED = "APPROVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class EventEntryRole(str, Enum):
    TEAM_RIDER = "TEAM_RIDER"
    PUBLIC = "PUBLIC"


class EventEntryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------- #
class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_price_cents: int
    rental_day_rate_cents: int
    is_rentable: bool
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    loyalty_points: int
    lifetime_spend_cents: int
    store_credit_cents: int
    tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict):
    id: str
    name: str
    discipline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalAsset(TypedDict):
    id: str
    product_id: str
    asset_tag: str
    condition: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lesson(TypedDict):
    id: str
    coach_id: str
    customer_id: str
    discipline: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Rental(TypedDict):
    id: str
    customer_id: str
    rental_asset_id: str
    lesson_id: Optional[str]
    start_at: str
    end_at: str
    deposit_cents: int
    rental_fee_cents: int
    late_fee_cents: int
    returned_at: Optional[str]
    fulfillment_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class BoardBuild(TypedDict):
    id: str
    customer_id: str
    components: List[dict]
    provisional_cost_cents: int
    final_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict):
    id: str
    customer_id: str
    board_description: str
    parts: List[dict]
    labor_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    customer_id: str
    item_description: str
    mode: str
    appraised_value_cents: int
    cash_offer_cents: int
    store_credit_offer_cents: int
    payout_choice: Optional[str]
    list_price_cents: int
    sold_price_cents: int
    consignor_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    quantity: int
    quoted_price_cents: int
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    name: str
    sponsor: str
    venue: str
    start_at: str
    capacity: int
    entry_fee_cents: int
    entry_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventEntry(TypedDict):
    id: str
    event_id: str
    customer_id: str
    role: str
    points_awarded: int
    status: str
    created_at: str
    updated_at: str
    version: int
