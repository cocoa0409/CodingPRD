"""Domain types: entity TypedDicts, status enums, and the role enum.

Derived from the PRD's entity model and state machines. Every persisted resource
carries id/created_at/updated_at/version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ---

class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    CLOSED = "CLOSED"


class LotStatus(str, Enum):
    AGING = "AGING"
    READY = "READY"
    DEPLETED = "DEPLETED"
    DISCARDED = "DISCARDED"


class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, Enum):
    NONE = "NONE"
    STORE_CREDIT = "STORE_CREDIT"
    EXTERNAL = "EXTERNAL"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class TastingEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    COUNTER_STAFF = "CounterStaff"
    WHOLESALE_CUSTOMER = "WholesaleCustomer"


# --- Entity TypedDicts (all entities carry common fields: id/created_at/updated_at/version) ---

class Customer(TypedDict):
    id: str
    account_type: str
    name: str
    region_code: str
    wholesale_tier: str
    credit_limit_cents: int
    store_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    name: str
    category: str
    milk_type: str
    pasteurized: bool
    form: str
    pricing_mode: str
    price_per_kg_cents: int
    unit_price_cents: int
    allergens: List[str]
    min_aging_days: int
    target_aging_days: int
    shrink_pct_per_day: float
    created_at: str
    updated_at: str
    version: int


class Cave(TypedDict):
    id: str
    name: str
    temp_c: float
    humidity_pct: float
    capacity_g: int
    used_g: int
    available_g: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    product_id: str
    cave_id: str
    received_weight_g: int
    current_weight_g: int
    reserved_weight_g: int
    available_weight_g: int
    consumed_weight_g: int
    cumulative_shrink_g: int
    projected_ready_weight_g: int
    aging_start_date: str
    last_aged_days: int
    aging_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    order_type: str
    customer_id: str
    prep_station_id: Optional[str]
    prep_window_start: Optional[str]
    prep_window_end: Optional[str]
    event_date: Optional[str]
    billable_weight_g: int
    subtotal_cents: int
    discount_cents: int
    delivery_fee_cents: int
    total_cents: int
    fulfillment_status: str
    payment_status: str
    payment_method: str
    store_credit_applied_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    line_type: str
    product_id: Optional[str]
    board_id: Optional[str]
    lot_id: Optional[str]
    requested_weight_g: int
    requested_qty: int
    actual_cut_weight_g: int
    reserved_weight_g: int
    provisional_price_cents: int
    final_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Board(TypedDict):
    id: str
    name: str
    components: List[dict]
    pairing_notes: Optional[str]
    assembly_fee_cents: int
    base_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    board_id: str
    tier: str
    cadence_days: int
    monthly_price_cents: int
    is_gift: bool
    gift_recipient_email: Optional[str]
    status: str
    next_ship_date: str
    created_at: str
    updated_at: str
    version: int


class PrepStation(TypedDict):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class TastingRoom(TypedDict):
    id: str
    name: str
    seat_capacity: int
    buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class TastingEvent(TypedDict):
    id: str
    tasting_room_id: str
    customer_id: str
    start_at: str
    end_at: str
    seats: int
    pairing_product_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int
