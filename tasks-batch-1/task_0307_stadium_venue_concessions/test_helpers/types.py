"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CONCESSIONS_MANAGER = "ConcessionsManager"
    STOCK_RUNNER = "StockRunner"
    STAND_OPERATOR = "StandOperator"
    PATRON = "Patron"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.3, §3.5, §3.8, §3.7)
# ---------------------------------------------------------------------------
class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DOORS_OPEN = "DOORS_OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    SETTLED = "SETTLED"


class StandStatus(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class InventoryLotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class ReplenishmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PICKING = "PICKING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TransferStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    CART = "CART"
    PLACED = "PLACED"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class StaffShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class ShareBasis(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class SpoilageValuation(str, Enum):
    FIFO = "FIFO"
    WEIGHTED_AVG = "WEIGHTED_AVG"


class DemandTier(str, Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"


class WasteReason(str, Enum):
    EXPIRY = "EXPIRY"
    SPILLAGE = "SPILLAGE"
    DAMAGE = "DAMAGE"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4, §3.x)
# All entities below carry common fields id/created_at/updated_at/version
# EXCEPT WasteRecord (PRD §2.4: id + created_at only).
# ---------------------------------------------------------------------------
class Venue(TypedDict):
    id: str
    name: str
    venue_share_pct: float
    service_fee_pct: float
    share_basis: str
    spoilage_valuation: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    venue_id: str
    sku: str
    name: str
    base_price_cents: int
    unit_cost_cents: int
    perishable: bool
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    venue_id: str
    name: str
    doors_time: str
    end_time: str
    event_multiplier_pct: int
    peak_window: bool
    status: str
    gross_sales_cents: int
    waste_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Stand(TypedDict):
    id: str
    event_id: str
    name: str
    demand_tier: str
    expected_orders_per_hour: int
    status: str
    required_staff: int
    assigned_staff_count: int
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    stand_id: str
    product_id: str
    available: bool
    price_cents: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    stand_id: str
    product_id: str
    received_qty: int
    remaining_qty: int
    unit_cost_cents: int
    par_level: int
    reorder_point: int
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Replenishment(TypedDict):
    id: str
    stand_id: str
    product_id: str
    requested_qty: int
    fulfilled_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Transfer(TypedDict):
    id: str
    from_stand_id: str
    to_stand_id: str
    product_id: str
    qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    event_id: str
    stand_id: str
    patron_id: str
    subtotal_cents: int
    service_fee_cents: int
    total_cents: int
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    menu_item_id: str
    qty: int
    unit_price_cents: int
    line_subtotal_cents: int
    line_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffShift(TypedDict):
    id: str
    stand_id: str
    worker_name: str
    shift_start: str
    shift_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# WasteRecord is immutable (PRD §2.4): only id + created_at, NO updated_at, NO version.
class WasteRecord(TypedDict):
    id: str
    stand_id: str
    product_id: str
    lot_id: Optional[str]
    reason: str
    qty: int
    cost_cents: int
    created_at: str


class RevenueShareStatement(TypedDict):
    id: str
    event_id: str
    gross_sales_cents: int
    waste_cost_cents: int
    venue_share_cents: int
    operator_net_cents: int
    created_at: str
    updated_at: str
    version: int


class Patron(TypedDict):
    id: str
    display_name: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int
