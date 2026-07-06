"""Domain types for the Bakery Cafe & Wholesale Bread API.

Entity TypedDicts, status enums, and the role enum. Envelope types are provided
by the framework and are not redefined here.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    MANAGER = "Manager"
    BAKER = "Baker"
    CASHIER = "Cashier"
    DRIVER = "Driver"
    WHOLESALE_CLIENT = "WholesaleClient"


# ------------------------------------------------------------------------ vocab enums
class ProductCategory(str, Enum):
    BREAD = "BREAD"
    PASTRY = "PASTRY"
    CAKE = "CAKE"
    SANDWICH = "SANDWICH"
    OTHER = "OTHER"


class Allergen(str, Enum):
    GLUTEN = "GLUTEN"
    DAIRY = "DAIRY"
    EGG = "EGG"
    NUT = "NUT"
    SOY = "SOY"
    SESAME = "SESAME"


class ContractTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    BULK = "BULK"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


# ---------------------------------------------------------------------- status enums
class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class OvenStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BakePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    BAKED = "BAKED"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"


class BakeLotStatus(str, Enum):
    FRESH = "FRESH"
    MARKED_DOWN = "MARKED_DOWN"
    SOLD_OUT = "SOLD_OUT"
    EXPIRED = "EXPIRED"


class WholesaleAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class StandingOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    PACKED = "PACKED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DeliveryRouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# -------------------------------------------------------------------- entity typeddicts
# common_fields: true entities carry id + created_at + updated_at + version.
class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    allergens: List[str]
    shelf_life_hours: int
    base_price_cents: int
    is_custom: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Oven(TypedDict):
    id: str
    name: str
    capacity_trays: int
    clean_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BakePlan(TypedDict):
    id: str
    production_date: str
    notes: Optional[str]
    status: str
    total_theoretical_waste_units: int
    total_actual_waste_units: int
    total_waste_value_cents: int
    created_at: str
    updated_at: str
    version: int


class BakePlanLine(TypedDict):
    id: str
    bake_plan_id: str
    product_id: str
    par_qty: int
    reserved_qty: int
    available_qty: int
    baked_qty: int
    sold_qty: int
    delivered_qty: int
    theoretical_waste_units: int
    actual_waste_units: int
    created_at: str
    updated_at: str
    version: int


class BakeLot(TypedDict):
    id: str
    bake_plan_line_id: str
    oven_id: str
    baked_qty: int
    remaining_qty: int
    produced_at: str
    best_by: str
    slot_start: str
    slot_end: str
    status: str
    markdown_price_cents: Optional[int]
    current_unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class WholesaleAccount(TypedDict):
    id: str
    name: str
    contract_tier: str
    credit_limit_cents: int
    credit_balance_cents: int
    allergen_restrictions: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StandingOrder(TypedDict):
    id: str
    wholesale_account_id: str
    product_id: str
    qty_per_delivery: int
    weekday_mask: List[str]
    cutoff_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryOrder(TypedDict):
    id: str
    wholesale_account_id: str
    standing_order_id: Optional[str]
    product_id: str
    bake_plan_line_id: str
    delivery_date: str
    qty: int
    unit_price_cents: int
    line_total_cents: int
    list_total_cents: int
    amount_paid_cents: int
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict):
    id: str
    route_date: str
    driver_name: str
    window_start: str
    window_end: str
    status: str
    stop_count: int
    total_load_qty: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    delivery_order_id: str
    sequence: int
    arrival_window_start: str
    arrival_window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable POS record: only id + created_at (no updated_at/version).
class RetailSale(TypedDict):
    id: str
    bake_lot_id: str
    qty: int
    unit_price_cents: int
    total_cents: int
    sold_at: str
    created_at: str
