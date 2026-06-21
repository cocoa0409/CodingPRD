"""Domain types: entity TypedDicts, status enums, role enum.

Every primary resource in this API is a versioned resource carrying id, created_at,
updated_at, and version (PRD §2.4), so every TypedDict below lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# ─── Status enums ─────────────────────────────────────────────────────────────

class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class OrderBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class ArtProofStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    VOID = "VOID"


class BlankReservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class ProductionRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class MethodType(str, Enum):
    SCREEN_PRINT = "SCREEN_PRINT"
    EMBROIDERY = "EMBROIDERY"


class ResourceKind(str, Enum):
    PRESS = "PRESS"
    EMBROIDERY_STATION = "EMBROIDERY_STATION"


class QuoteVariant(str, Enum):
    ESTIMATE = "ESTIMATE"


class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    ART_STAFF = "ArtStaff"
    CUSTOMER = "Customer"
    SYSTEM = "System"


# ─── Entity TypedDicts (all versioned resources, PRD §2.4) ────────────────────

class Shop(TypedDict):
    id: str
    name: str
    current_utc: str
    spoilage_pct: float
    rush_threshold_days: int
    rush_surcharge_pct: float
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    shop_id: str
    name: str
    email: str
    outstanding_deposit_cents: int
    archived: bool
    created_at: str
    updated_at: str
    version: int


class DecorationMethod(TypedDict):
    id: str
    shop_id: str
    method_type: str
    name: str
    screen_fee_cents: int
    digitizing_fee_cents: int
    extra_color_run_cents: int
    stitch_run_per_1k_cents: int
    resource_kind: str
    created_at: str
    updated_at: str
    version: int


class GarmentStyle(TypedDict):
    id: str
    shop_id: str
    sku_code: str
    name: str
    blank_cost_cents: int
    available_colors: List[str]
    available_sizes: List[str]
    created_at: str
    updated_at: str
    version: int


class BlankSku(TypedDict):
    id: str
    garment_style_id: str
    color: str
    size: str
    total_stock_qty: int
    on_hand_qty: int
    reserved_qty: int
    created_at: str
    updated_at: str
    version: int


class Press(TypedDict):
    id: str
    shop_id: str
    name: str
    teardown_buffer_min: int
    created_at: str
    updated_at: str
    version: int


class EmbroideryStation(TypedDict):
    id: str
    shop_id: str
    name: str
    head_count: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    shop_id: str
    customer_id: str
    reorder_of_order_id: Optional[str]
    requested_ship_date: str
    is_rush: bool
    fulfillment_status: str
    billing_status: str
    deposit_paid_cents: int
    final_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    garment_style_id: str
    decoration_method_id: str
    color: str
    num_locations: int
    num_colors: int
    stitch_count: int
    size_run: Dict[str, int]
    line_qty: int
    created_at: str
    updated_at: str
    version: int


class ArtProof(TypedDict):
    id: str
    order_id: str
    title: str
    art_hash: str
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BlankReservation(TypedDict):
    id: str
    order_id: str
    blank_sku_id: str
    ordered_qty: int
    allowance_qty: int
    reserved_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    order_id: str
    blank_subtotal_cents: int
    setup_subtotal_cents: int
    decoration_subtotal_cents: int
    rush_surcharge_cents: int
    grand_total_cents: int
    variant: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    order_id: str
    press_id: Optional[str]
    embroidery_station_id: Optional[str]
    window_start: str
    window_end: str
    good_units: Optional[int]
    spoiled_units: Optional[int]
    consumed_units: Optional[int]
    released_units: Optional[int]
    blanks_pulled: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
