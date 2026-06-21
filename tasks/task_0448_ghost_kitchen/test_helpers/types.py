"""Domain types: entity TypedDicts, status enums, role enum (Ghost Kitchen Platform)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ── Status / enum domains ────────────────────────────────────────────────────

class StallStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BrandStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class BrandAvailability(str, Enum):
    LISTED = "LISTED"
    PAUSED = "PAUSED"


class LeaseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EquipmentType(str, Enum):
    FRYER = "FRYER"
    OVEN = "OVEN"
    GRILL = "GRILL"
    PREP_STATION = "PREP_STATION"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class BookingStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class MenuItemAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    SOLD_OUT = "SOLD_OUT"


class Aggregator(str, Enum):
    DOORDASH = "DOORDASH"
    UBER_EATS = "UBER_EATS"


class OrderStatus(str, Enum):
    INGESTED = "INGESTED"
    ROUTED = "ROUTED"
    PREPARING = "PREPARING"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    PLATFORM_OPS = "PlatformOps"
    STALL_OPERATOR = "StallOperator"
    BRAND_OWNER = "BrandOwner"
    AGGREGATOR_GATEWAY = "AggregatorGateway"


# ── Entity TypedDicts ────────────────────────────────────────────────────────
# Versioned entities (common_fields: true) carry id/created_at/updated_at/version.

class Stall(TypedDict):
    id: str
    name: str
    timezone: str
    open_minute_of_day: int
    close_minute_of_day: int
    status: str
    equipment_count: int
    created_at: str
    updated_at: str
    version: int


class VirtualBrand(TypedDict):
    id: str
    name: str
    owner_email: str
    commission_rate_bps: int
    availability: str
    status: str
    ledger_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class KitchenLease(TypedDict):
    id: str
    stall_id: str
    brand_id: str
    monthly_fee_cents: int
    priority_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    stall_id: str
    equipment_type: str
    turnaround_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentBooking(TypedDict):
    id: str
    equipment_id: str
    order_id: Optional[str]
    start_minute: int
    end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    brand_id: str
    name: str
    price_cents: int
    prep_minutes: int
    required_equipment_type: str
    availability: str
    created_at: str
    updated_at: str
    version: int


# RecipeComponent (common_fields: false) — immutable line; ONLY id + created_at,
# NO updated_at, NO version.
class RecipeComponent(TypedDict):
    id: str
    menu_item_id: str
    ingredient_name: str
    quantity_grams: int
    created_at: str


class IngredientLot(TypedDict):
    id: str
    stall_id: str
    ingredient_name: str
    received_at: str
    unit_cost_cents_per_gram: int
    grams_received: int
    grams_remaining: int
    created_at: str
    updated_at: str
    version: int


class AggregatorOrder(TypedDict):
    id: str
    brand_id: str
    aggregator: str
    external_ref: str
    line_items: List[dict]
    routed_stall_id: Optional[str]
    booking_id: Optional[str]
    gross_revenue_cents: int
    commission_cents: int
    food_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
