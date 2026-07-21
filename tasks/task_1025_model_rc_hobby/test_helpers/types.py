"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in the platform carries the four common system fields
(id, created_at, updated_at, version), so each TypedDict lists them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    STORE_STAFF = "StoreStaff"
    STORE_MANAGER = "StoreManager"


# --- Value enums ---
class ProductType(str, Enum):
    KIT = "KIT"
    RC_VEHICLE = "RC_VEHICLE"
    PART = "PART"
    BATTERY = "BATTERY"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


# --- Status enums ---
class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ALLOCATING = "ALLOCATING"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    ALLOCATED = "ALLOCATED"
    WAITLISTED = "WAITLISTED"
    CONVERTED = "CONVERTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ServiceJobStatus(str, Enum):
    RECEIVED = "RECEIVED"
    DIAGNOSING = "DIAGNOSING"
    AWAITING_PARTS = "AWAITING_PARTS"
    IN_PROGRESS = "IN_PROGRESS"
    QC = "QC"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class JobType(str, Enum):
    BUILD = "BUILD"
    REPAIR = "REPAIR"


class RaceEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class RaceEntryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    RACED = "RACED"
    DISQUALIFIED = "DISQUALIFIED"
    WITHDRAWN = "WITHDRAWN"


class RaceClass(str, Enum):
    STOCK = "STOCK"
    MODIFIED = "MODIFIED"
    PRO = "PRO"


# --- Entity TypedDicts (all entities carry the four common fields) ---
class Customer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    email: str
    full_name: str
    lifetime_spend_cents: int
    loyalty_points_balance: int
    loyalty_tier: str
    hazmat_safety_ack: bool


class Product(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    sku: str
    name: str
    product_type: str
    price_cents: int
    stock_on_hand: int
    is_hazmat: bool


class PreOrderCampaign(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    product_id: str
    title: str
    total_allocation_units: int
    unit_price_cents: int
    reservation_open_at: str
    reservation_close_at: str
    allocated_units: int
    remaining_units: int
    status: str


class PreOrderReservation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    campaign_id: str
    customer_id: str
    requested_units: int
    allocated_units: int
    order_id: Optional[str]
    status: str


class Order(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    customer_id: str
    source: str
    lines: List[dict]
    subtotal_cents: int
    discount_cents: int
    hazmat_surcharge_cents: int
    total_cents: int
    amount_paid_cents: int
    provisional_points: int
    final_points: int
    status: str
    payment_status: str
    fulfillment_status: str


class ServiceJob(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    customer_id: str
    product_id: Optional[str]
    job_type: str
    bench_code: Optional[str]
    slot_start: Optional[str]
    slot_end: Optional[str]
    estimated_labor_hours: Optional[float]
    estimated_parts_cents: int
    actual_labor_hours: Optional[float]
    actual_parts_cents: Optional[int]
    rework_count: int
    provisional_quote_cents: int
    final_invoice_cents: int
    status: str


class RaceEvent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    event_date: str
    capacity: int
    lane_count: int
    entry_fee_cents: int
    registration_open_at: str
    registration_close_at: str
    entry_count: int
    status: str


class RaceEntry(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    event_id: str
    customer_id: str
    race_class: str
    lane_no: int
    heat_start: str
    heat_end: str
    entry_points_awarded: int
    status: str
