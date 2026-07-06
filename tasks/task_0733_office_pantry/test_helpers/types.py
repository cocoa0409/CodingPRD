"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class SubscriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class RotationCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    INVALIDATED = "INVALIDATED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class InvoicePaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    DEFAULT = "DEFAULT"


class InvoiceDisputeStatus(str, Enum):
    CLEAN = "CLEAN"
    UNDER_DISPUTE = "UNDER_DISPUTE"
    RESOLVED = "RESOLVED"


class BillingType(str, Enum):
    PER_EMPLOYEE = "PER_EMPLOYEE"
    FLAT = "FLAT"


class LocationKind(str, Enum):
    PANTRY = "PANTRY"
    FRIDGE = "FRIDGE"
    MICRO_MARKET = "MICRO_MARKET"


class ProductCategory(str, Enum):
    SNACK = "SNACK"
    BEVERAGE = "BEVERAGE"
    MEAL = "MEAL"
    CANDY = "CANDY"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLIENT_ADMIN = "ClientAdmin"
    LOCATION_MANAGER = "LocationManager"


# --- Entities with common_fields: true (id, created_at, updated_at, version) ---

class Client(TypedDict):
    id: str
    name: str
    headcount: int
    credit_balance_cents: int
    active_subscription_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict):
    id: str
    tier: str
    billing_type: str
    base_fee_cents: int
    per_employee_fee_cents: int
    flat_fee_cents: int
    volume_discount_threshold_headcount: int
    volume_discount_pct: float
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    client_id: str
    plan_id: str
    plan_version_snapshot: int
    status: str
    paused_at: Optional[str]
    cancelled_at: Optional[str]
    cumulative_active_days: int
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    client_id: str
    name: str
    kind: str
    capacity_units: int
    service_fee_bps: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    dietary_flags: List[str]
    unit_cost_cents: int
    requires_refrigeration: bool
    created_at: str
    updated_at: str
    version: int


class ParLevel(TypedDict):
    id: str
    location_id: str
    product_id: str
    par_units: int
    created_at: str
    updated_at: str
    version: int


class RotationCycle(TypedDict):
    id: str
    subscription_id: str
    cycle_index: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    location_id: str
    rotation_cycle_id: str
    scheduled_at: str
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    status: str
    dispute_reason: Optional[str]
    provisional_cents: int
    final_cents: int
    dispute_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliveryLine(TypedDict):
    id: str
    delivery_id: str
    product_id: str
    planned_units: int
    actual_units: Optional[int]
    unit_price_cents_snapshot: int
    service_fee_bps_snapshot: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    client_id: str
    rotation_cycle_id: str
    period_start: str
    period_end: str
    subscription_fee_cents: int
    consumption_cents: int
    credit_applied_cents: int
    total_cents: int
    payment_status: str
    dispute_status: str
    created_at: str
    updated_at: str
    version: int


# --- Entities with common_fields: false (id, created_at only) ---

class Preference(TypedDict):
    id: str
    client_id: str
    dietary_flag: str
    created_at: str


class Feedback(TypedDict):
    id: str
    client_id: str
    product_id: str
    rating: int
    comment: Optional[str]
    swap_suggestion_product_id: Optional[str]
    created_at: str
