"""Domain types: entity TypedDicts, status enums, and the role enum.

All names use the Food Truck Operations & Permits domain vocabulary from the PRD.
"""
from enum import Enum
from typing import TypedDict, List


# ─── Status enums ──────────────────────────────────────────────────────────

class CommissaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class HealthPermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class OperabilityPosture(str, Enum):
    OPERABLE = "OPERABLE"
    RESTRICTED = "RESTRICTED"
    GROUNDED = "GROUNDED"


class MenuItemStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNLISTED = "UNLISTED"


class PrepBatchStatus(str, Enum):
    OPEN = "OPEN"
    DISCARDED = "DISCARDED"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    ARRIVED = "ARRIVED"
    DEPARTED = "DEPARTED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class OrderLifecycleStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    VOID = "VOID"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class StaffShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class StaffRole(str, Enum):
    DRIVER = "DRIVER"
    COOK = "COOK"
    CASHIER = "CASHIER"


class UtilityKind(str, Enum):
    PROPANE = "PROPANE"
    GENERATOR = "GENERATOR"


class DiscountCode(str, Enum):
    NONE = "NONE"
    HAPPY_HOUR = "HAPPY_HOUR"
    BULK10 = "BULK10"


class UserRole(str, Enum):
    OperatorTruck = "OperatorTruck"
    Dispatcher = "Dispatcher"
    HealthInspector = "HealthInspector"
    PlatformAdmin = "PlatformAdmin"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# Full-record entities carry id + created_at + updated_at + version.
# The single append-only entity (UtilityLog) carries only id + created_at.

class Commissary(TypedDict):
    id: str
    name: str
    state_code: str
    status: str
    docked_truck_count: int
    created_at: str
    updated_at: str
    version: int


class HealthPermit(TypedDict):
    id: str
    truck_id: str
    permit_number: str
    state_code: str
    status: str
    issued_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class OperatorTruck(TypedDict):
    id: str
    commissary_id: str
    name: str
    home_state_code: str
    operability: str
    propane_psi: float
    generator_runtime_hours: float
    reservation_fee_balance_cents: int
    gross_sales_cents: int
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    truck_id: str
    sku: str
    name: str
    unit_price_cents: int
    par_units: int
    prepared_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrepBatch(TypedDict):
    id: str
    truck_id: str
    menu_item_id: str
    units_made: int
    prepped_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Spot(TypedDict):
    id: str
    name: str
    state_code: str
    concurrent_capacity: int
    buffer_minutes: int
    reservation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    name: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    truck_id: str
    spot_id: str
    event_id: str
    window_start: str
    window_end: str
    status: str
    reservation_fee_cents: int
    fee_refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    truck_id: str
    booking_id: str
    lifecycle_status: str
    payment_status: str
    tip_cents: int
    discount_code: str
    live_total_cents: int
    settled_total_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    menu_item_id: str
    quantity: int
    unit_price_cents: int
    line_subtotal_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffShift(TypedDict):
    id: str
    truck_id: str
    staff_name: str
    role: str
    shift_start: str
    shift_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only event record — only id + created_at, NO updated_at / version.
class UtilityLog(TypedDict):
    id: str
    truck_id: str
    utility: str
    propane_psi_after: float
    generator_delta_hours: float
    logged_at: str
    created_at: str


class SalesReport(TypedDict):
    event_id: str
    gross_sales_cents: int
    order_count: int
    total_tips_cents: int
    net_reservation_cents: int
    truck_breakdown: List[dict]
