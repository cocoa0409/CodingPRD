"""Domain types for the Cloth Diaper & Linen Route Service API.

Entity field sets mirror the resources described in PRD 2.4 and section 3.
Every resource in this API carries the common system-managed fields
(`id`, `created_at`, `updated_at`, `version`), so every TypedDict below
includes them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER = "Customer"
    ROUTE_DRIVER = "RouteDriver"
    PLANT_OPERATOR = "PlantOperator"
    BILLING_ADMIN = "BillingAdmin"


class SizeCode(str, Enum):
    NEWBORN = "NEWBORN"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    XL = "XL"


class WeightPolicy(str, Enum):
    COUNT_BASIS = "COUNT_BASIS"
    WEIGHT_BASIS = "WEIGHT_BASIS"


class CustomerStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ServiceStatus(str, Enum):
    PENDING_START = "PENDING_START"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"


class PauseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class KitStatus(str, Enum):
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    SETTLED = "SETTLED"


class SwapStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    STAGED = "STAGED"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    SEQUENCED = "SEQUENCED"
    LOCKED = "LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    SKIPPED = "SKIPPED"
    FORFEITED = "FORFEITED"
    RESCHEDULED = "RESCHEDULED"


class IntakeStatus(str, Enum):
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class IntakeResolution(str, Enum):
    ACCEPT_COUNT = "ACCEPT_COUNT"
    ACCEPT_WEIGHT = "ACCEPT_WEIGHT"


class SoilLevel(str, Enum):
    LIGHT = "LIGHT"
    NORMAL = "NORMAL"
    HEAVY = "HEAVY"


class WaterHardness(str, Enum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class BatchStatus(str, Enum):
    RECEIVING = "RECEIVING"
    LOADED = "LOADED"
    WASHING = "WASHING"
    VALIDATING = "VALIDATING"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"


class CaseType(str, Enum):
    LOST = "LOST"
    DAMAGED = "DAMAGED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    CHARGED = "CHARGED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    VOID = "VOID"
    WRITTEN_OFF = "WRITTEN_OFF"


class SubscriptionPlan(TypedDict):
    id: str
    tier_code: str
    weekly_quota: int
    weekly_fee_cents: int
    overage_rate_cents: int
    overage_cap_items: int
    deposit_cents: int
    service_bags_per_week: int
    weight_policy: str
    kit_reserve_pct: int
    created_at: str
    updated_at: str
    version: int


class ServiceZone(TypedDict):
    id: str
    zone_code: str
    service_weekdays: List[str]
    service_days_per_week: int
    stop_cutoff_hours: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    service_zone_id: str
    child_birthdate: str
    child_size_code: str
    status: str
    deposit_charged_cents: int
    deposit_held_cents: int
    deposit_applied_cents: int
    deposit_refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    subscription_plan_id: str
    service_zone_id: str
    start_date: str
    current_size_code: str
    window_start_minutes: int
    window_end_minutes: int
    service_status: str
    billing_status: str
    missed_stop_count: int
    created_at: str
    updated_at: str
    version: int


class ServicePause(TypedDict):
    id: str
    subscription_id: str
    start_date: str
    end_date: str
    status: str
    estimated_credit_cents: int
    final_credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StarterKit(TypedDict):
    id: str
    subscription_id: str
    size_code: str
    item_count: int
    items_returned_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryPool(TypedDict):
    id: str
    size_code: str
    on_hand_units: int
    reserved_units: int
    in_transit_units: int
    checked_out_units: int
    in_wash_units: int
    quarantined_units: int
    lost_units: int
    retired_units: int
    total_acquired_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class InventorySwap(TypedDict):
    id: str
    subscription_id: str
    from_size_code: str
    to_size_code: str
    quantity: int
    returned_old_count: int
    shortage_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    service_zone_id: str
    route_date: str
    status: str
    planned_stop_count: int
    completed_stop_count: int
    total_clean_items_delivered: int
    total_soiled_bags_collected: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    subscription_id: str
    stop_seq: Optional[int]
    window_start_minutes: int
    window_end_minutes: int
    status: str
    clean_items_delivered: int
    soiled_bags_collected: int
    is_makeup: bool
    rescheduled_to_stop_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SoiledIntake(TypedDict):
    id: str
    route_stop_id: str
    wash_batch_id: Optional[str]
    scale_weight_g: int
    soil_level: str
    expected_weight_g: int
    variance_pct: float
    verified_count: int
    status: str
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WashFormula(TypedDict):
    id: str
    formula_code: str
    base_detergent_ml_per_kg: int
    sanitizer_ml_per_kg: int
    min_temp_celsius: int
    min_dwell_seconds: int
    chlorine_ppm_min: int
    chlorine_ppm_max: int
    max_rewash_count: int
    created_at: str
    updated_at: str
    version: int


class WashBatch(TypedDict):
    id: str
    wash_formula_id: str
    formula_version: int
    soil_level: str
    water_hardness: str
    status: str
    total_load_g: int
    dosed_detergent_ml: Optional[int]
    dosed_sanitizer_ml: Optional[int]
    rewash_count: int
    wash_started_by: Optional[str]
    validated_by: Optional[str]
    validation_passed: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class LostItemCase(TypedDict):
    id: str
    subscription_id: str
    inventory_pool_id: str
    case_type: str
    item_count: int
    first_issued_date: str
    assessed_fee_cents: Optional[int]
    charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    subscription_id: str
    period_start: str
    period_end: str
    status: str
    base_fee_cents: int
    overage_cents: int
    pause_credit_cents: int
    total_cents: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
