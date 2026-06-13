"""Domain types: entity TypedDicts, status enums, role enum for the BOPIS / curbside API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ----------------------------------------------------------

class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PICKING = "PICKING"
    STAGED = "STAGED"
    AWAITING_PICKUP = "AWAITING_PICKUP"
    PARTIALLY_PICKED_UP = "PARTIALLY_PICKED_UP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class OrderPaymentStatus(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    SHORT_PICKED = "SHORT_PICKED"
    PICKED = "PICKED"
    SUBSTITUTION_PROPOSED = "SUBSTITUTION_PROPOSED"
    SUBSTITUTED = "SUBSTITUTED"
    HANDED_OVER = "HANDED_OVER"
    NOT_FULFILLED = "NOT_FULFILLED"


class SubstitutionDecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class CurbsideCheckInStatus(str, Enum):
    ARRIVED = "ARRIVED"
    BEING_LOADED = "BEING_LOADED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SlotFillStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class PickupStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    BLOCKED = "BLOCKED"


class MovementType(str, Enum):
    RESTOCK = "RESTOCK"
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"
    PICK_REMOVE = "PICK_REMOVE"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    STORE_PICKER = "StorePicker"
    STORE_ASSOCIATE = "StoreAssociate"
    STORE_MANAGER = "StoreManager"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ---

class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    phone: str
    no_show_strikes: int
    pickup_standing: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    name: str
    state_code: str
    curbside_spaces: int
    hold_window_minutes: int
    active_curbside_count: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    unit_price_cents: int
    substitution_group: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StoreInventory(TypedDict):
    id: str
    store_id: str
    product_id: str
    on_hand: int
    reserved: int
    available: int
    created_at: str
    updated_at: str
    version: int


class PickupSlot(TypedDict):
    id: str
    store_id: str
    window_start: str
    window_end: str
    cutoff_offset_minutes: int
    capacity: int
    booked_count: int
    fill_status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    store_id: str
    slot_id: Optional[str]
    fulfillment_status: str
    payment_status: str
    authorized_total_cents: int
    captured_total_cents: int
    refunded_total_cents: int
    verified: bool
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    qty_ordered: int
    qty_reserved: int
    qty_picked: int
    qty_handed_over: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


class Substitution(TypedDict):
    id: str
    order_line_id: str
    substitute_product_id: str
    substitute_qty: int
    decision_status: str
    price_delta_cents: int
    created_at: str
    updated_at: str
    version: int


class Hold(TypedDict):
    id: str
    order_id: str
    store_id: str
    staged_at: str
    expires_at: str
    hold_status: str
    created_at: str
    updated_at: str
    version: int


class CurbsideCheckIn(TypedDict):
    id: str
    order_id: str
    store_id: str
    vehicle_description: str
    checkin_status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger entities (common_fields: false → only id + created_at) ---

class PickupEvent(TypedDict):
    id: str
    order_id: str
    order_line_id: str
    qty_handed_over: int
    captured_cents: int
    created_at: str


class InventoryMovement(TypedDict):
    id: str
    store_inventory_id: str
    movement_type: str
    delta_on_hand: int
    delta_reserved: int
    reason: str
    created_at: str
