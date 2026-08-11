"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCHER = "Dispatcher"
    CUSTOMER = "Customer"
    MECHANIC = "Mechanic"


class AccountKind(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FLEET = "FLEET"
    APARTMENT = "APARTMENT"


class BikeType(str, Enum):
    MECHANICAL = "MECHANICAL"
    EBIKE = "EBIKE"


class MechanicStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class StockMovementReason(str, Enum):
    RECEIVE = "RECEIVE"
    RETURN_TO_WAREHOUSE = "RETURN_TO_WAREHOUSE"
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"
    CONSUME = "CONSUME"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class WorkStatus(str, Enum):
    QUOTED = "QUOTED"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    IN_SERVICE = "IN_SERVICE"
    ON_HOLD_PARTS = "ON_HOLD_PARTS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BillingStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    INVOICED = "INVOICED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class RequestKind(str, Enum):
    STANDARD = "STANDARD"
    CALLBACK = "CALLBACK"


class RouteDayStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class RouteStopStatus(str, Enum):
    PLANNED = "PLANNED"
    ARRIVED = "ARRIVED"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    UNASSIGNED = "UNASSIGNED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOID = "VOID"


class Zone(TypedDict, total=False):
    id: str
    name: str
    base_callout_fee_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    name: str
    email: str
    account_kind: str
    phone: Optional[str]
    account_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Bike(TypedDict, total=False):
    id: str
    customer_id: str
    bike_type: str
    brand: Optional[str]
    battery_wh: Optional[int]
    battery_certified: bool
    battery_health_pct: int
    created_at: str
    updated_at: str
    version: int


class Mechanic(TypedDict, total=False):
    id: str
    name: str
    ebike_certified: bool
    home_zone_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Van(TypedDict, total=False):
    id: str
    plate: str
    zone_id: str
    mechanic_id: Optional[str]
    max_stops_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    sku: str
    name: str
    unit_price_cents: int
    warranty_days: int
    ebike_only: bool
    created_at: str
    updated_at: str
    version: int


class TruckStockItem(TypedDict, total=False):
    id: str
    van_id: str
    part_id: str
    on_hand: int
    reserved: int
    created_at: str
    updated_at: str
    version: int


class StockMovement(TypedDict, total=False):
    # Append-only event log: carries ONLY id + created_at (no updated_at, no version)
    id: str
    van_id: str
    part_id: str
    service_request_id: Optional[str]
    quantity_delta: int
    reason: str
    note: Optional[str]
    created_at: str


class ServiceTier(TypedDict, total=False):
    id: str
    code: str
    base_price_cents: int
    included_minutes: int
    overage_rate_cents_per_min: int
    labor_warranty_days: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    customer_id: str
    included_tunes_per_period: int
    discount_pct: float
    period_start: str
    period_end: str
    status: str
    allowance_reserved: int
    allowance_consumed: int
    allowance_remaining: int
    settled_allowance_remaining: int
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict, total=False):
    id: str
    customer_id: str
    bike_id: str
    zone_id: str
    tier_id: str
    subscription_id: Optional[str]
    request_kind: str
    callback_of_id: Optional[str]
    window_start: str
    window_end: str
    issue_note: Optional[str]
    work_status: str
    billing_status: str
    scheduled_mechanic_id: Optional[str]
    quoted_total_cents: int
    covered_by_subscription: bool
    actual_labor_minutes: Optional[int]
    completed_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteDay(TypedDict, total=False):
    id: str
    van_id: str
    date: str
    status: str
    active_stop_count: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_day_id: str
    service_request_id: str
    seq: int
    planned_start: str
    planned_end: str
    travel_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    service_request_id: str
    status: str
    callout_cents: int
    labor_cents: int
    parts_gross_cents: int
    discount_cents: int
    subtotal_cents: int
    surcharge_cents: int
    tax_cents: int
    total_cents: int
    credit_applied_cents: int
    amount_paid_cents: int
    line_items: List[Dict[str, Any]]
    is_no_show_fee: bool
    created_at: str
    updated_at: str
    version: int
