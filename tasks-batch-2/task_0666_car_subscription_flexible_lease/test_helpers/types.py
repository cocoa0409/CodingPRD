"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum members mirror the Car Subscription & Flexible Lease PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FLEET_OPERATOR = "FleetOperator"
    BILLING_ADMIN = "BillingAdmin"
    MEMBER = "Member"


# --- Status enums ---
class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ASSIGNED = "ASSIGNED"
    IN_INSPECTION = "IN_INSPECTION"
    MAINTENANCE = "MAINTENANCE"


class EligibilityStatus(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    DECLINED = "DECLINED"


class LifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_DELIVERY = "PENDING_DELIVERY"
    ACTIVE = "ACTIVE"
    RETURN_PENDING = "RETURN_PENDING"
    CLOSED = "CLOSED"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"


class BillingCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class InvoiceSourceKind(str, Enum):
    CYCLE = "CYCLE"
    SWAP = "SWAP"
    EARLY_CANCEL = "EARLY_CANCEL"
    RETURN_SETTLEMENT = "RETURN_SETTLEMENT"


class SwapStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class InspectionStatus(str, Enum):
    OPEN = "OPEN"
    ASSESSED = "ASSESSED"
    SETTLED = "SETTLED"


class DamageSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class SlotKind(str, Enum):
    DELIVERY = "DELIVERY"
    RETURN = "RETURN"


class SlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (common_fields: true unless noted) ---
class SubscriptionPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    included_miles_per_cycle: int
    free_buffer_miles: int
    overage_tier1_rate_cents: int
    overage_tier2_rate_cents: int
    included_swaps_per_term: int
    min_term_months: int
    deposit_base_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Fleet(TypedDict):
    id: str
    name: str
    region_code: str
    total_vehicles: int
    in_use_count: int
    utilization_pct: float
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    fleet_id: str
    plan_id: str
    vin: str
    model_label: str
    odometer_miles: int
    status: str
    active_subscription_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    credit_score: int
    monthly_income_cents: int
    history_flag: str
    eligibility_status: Optional[str]
    eligibility_score: Optional[float]
    required_deposit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    applicant_id: str
    plan_id: str
    active_vehicle_id: Optional[str]
    lifecycle_status: str
    billing_status: str
    deposit_held_cents: int
    swaps_used: int
    cycle_start_iso: Optional[str]
    term_start_iso: Optional[str]
    lifetime_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict):
    id: str
    subscription_id: str
    vehicle_id: str
    cycle_index: int
    cycle_start_iso: str
    cycle_end_iso: Optional[str]
    odometer_start_miles: int
    odometer_end_miles: Optional[int]
    status: str
    overage_cents: int
    created_at: str
    updated_at: str
    version: int


# Invoice — common_fields: false: carries ONLY id + created_at (no updated_at, no version)
class Invoice(TypedDict):
    id: str
    subscription_id: str
    source_kind: str
    source_ref_id: str
    amount_cents: int
    posted_at_iso: str
    created_at: str


class SwapRequest(TypedDict):
    id: str
    subscription_id: str
    from_vehicle_id: str
    to_vehicle_id: str
    status: str
    swap_fee_applied_cents: int
    net_adjustment_cents: int
    created_at: str
    updated_at: str
    version: int


class ReturnInspection(TypedDict):
    id: str
    subscription_id: str
    vehicle_id: str
    status: str
    reported_odometer_miles: int
    total_damage_cents: int
    deposit_applied_cents: int
    deposit_refunded_cents: int
    balance_due_cents: int
    created_at: str
    updated_at: str
    version: int


class DamageLineItem(TypedDict):
    id: str
    inspection_id: str
    severity: str
    amount_cents: int
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Courier(TypedDict):
    id: str
    name: str
    fleet_id: str
    buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class DeliverySlot(TypedDict):
    id: str
    courier_id: str
    subscription_id: str
    kind: str
    window_start_iso: str
    window_end_iso: str
    status: str
    created_at: str
    updated_at: str
    version: int
