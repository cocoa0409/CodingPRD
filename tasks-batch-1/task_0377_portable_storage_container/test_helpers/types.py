"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    DISPATCH_OPERATOR = "DispatchOperator"
    BILLING_CLERK = "BillingClerk"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status enums (PRD §3) ---

class AgreementLifecycle(str, Enum):
    QUOTED = "QUOTED"
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    DELINQUENT = "DELINQUENT"


class ContainerUnitStatus(str, Enum):
    RESERVED = "RESERVED"
    DELIVERED = "DELIVERED"
    ON_SITE = "ON_SITE"
    IN_TRANSIT = "IN_TRANSIT"
    RETURNED = "RETURNED"
    RELEASED = "RELEASED"


class DeliveryJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MoveOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MoveClass(str, Enum):
    LOCAL = "LOCAL"
    LONG_DISTANCE = "LONG_DISTANCE"


class AccessVisitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class AccessKind(str, Enum):
    ON_SITE = "ON_SITE"
    DEPOT_PICKUP = "DEPOT_PICKUP"


class PackingSupplyOrderStatus(str, Enum):
    PLACED = "PLACED"
    CANCELLED = "CANCELLED"


class ChargeType(str, Enum):
    DELIVERY_FEE = "DELIVERY_FEE"
    RENTAL_PRORATION = "RENTAL_PRORATION"
    RENTAL_CYCLE = "RENTAL_CYCLE"
    PROTECTION_PREMIUM = "PROTECTION_PREMIUM"
    PACKING_SUPPLIES = "PACKING_SUPPLIES"
    MOVE = "MOVE"
    ACCESS_FEE = "ACCESS_FEE"
    LATE_FEE = "LATE_FEE"
    PAYMENT = "PAYMENT"
    ADJUSTMENT = "ADJUSTMENT"


class SizeCode(str, Enum):
    C8 = "C8"
    C12 = "C12"
    C16 = "C16"


class ProtectionTier(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


# --- Entity TypedDicts ---
# Immutable catalog entities (PRD §2.4: only id + created_at, no updated_at/version).

class ContainerModel(TypedDict):
    id: str
    created_at: str
    size_code: str
    cubic_feet: int
    monthly_rate_cents: int
    delivery_fee_cents: int
    footprint_sqft: int


class ProtectionPlan(TypedDict):
    id: str
    created_at: str
    tier_code: str
    base_premium_cents: int
    rate_bps: int
    min_premium_cents: int
    coverage_cap_cents: int


# Mutable entities (PRD §2.4: id + created_at + updated_at + version).

class Depot(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    state_code: str
    service_radius_miles: int


class DepotInventory(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    depot_id: str
    size_code: str
    total_units: int
    reserved_units: int
    committed_units: int
    available_units: int


class Customer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    email: str
    full_name: str
    state_code: str
    lifetime_paid_cents: int
    open_balance_cents: int


class RentalAgreement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    customer_id: str
    depot_id: str
    size_code: str
    protection_tier_code: str
    declared_value_cents: int
    proration_method: str
    site_address: str
    site_clearance_sqft: int
    lifecycle_status: str
    billing_status: str
    delivery_anchor_date: Optional[str]
    monthly_premium_cents: int
    balance_due_cents: int
    last_charged_cycle_date: Optional[str]
    days_overdue: int


class ContainerUnit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    depot_inventory_id: str
    size_code: str
    status: str
    current_depot_id: str


class Crew(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    depot_id: str
    name: str
    setup_buffer_minutes: int


class Truck(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    depot_id: str
    plate: str
    max_concurrent_containers: int


class DeliveryJob(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    crew_id: str
    container_unit_id: str
    job_kind: str
    window_start: str
    window_end: str
    status: str


class MoveOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    truck_id: str
    container_unit_id: str
    origin_depot_id: str
    destination_state_code: str
    distance_miles: int
    move_class: str
    window_start: str
    window_end: str
    quoted_cost_cents: int
    status: str


class AccessVisit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    container_unit_id: str
    access_kind: str
    requested_for: str
    redelivery_required: bool
    status: str


class PackingSupplyOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    lines: List[dict]
    tax_rate_bps: int
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    status: str


class Charge(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    charge_type: str
    amount_cents: int
    due_date: Optional[str]
    settled: bool
