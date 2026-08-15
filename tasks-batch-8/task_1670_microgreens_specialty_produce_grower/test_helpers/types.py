"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    GROWER = "Grower"
    CHEF = "Chef"
    OPS_MANAGER = "OpsManager"


class VarietyStage(str, Enum):
    TRIAL = "TRIAL"
    EVALUATION = "EVALUATION"
    LISTED = "LISTED"
    RETIRED = "RETIRED"


class TrialDecision(str, Enum):
    PENDING = "PENDING"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"


class SeedLotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    BLOCKED = "BLOCKED"
    DEPLETED = "DEPLETED"


class GerminationResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class CropPlanStatus(str, Enum):
    PLANNED = "PLANNED"
    SOWING = "SOWING"
    GROWING = "GROWING"
    READY = "READY"
    HARVESTED = "HARVESTED"
    CANCELLED = "CANCELLED"


class TrayBatchStatus(str, Enum):
    SOWN = "SOWN"
    GERMINATING = "GERMINATING"
    GROWING = "GROWING"
    READY = "READY"
    HARVESTED = "HARVESTED"
    FAILED = "FAILED"


class FoodSafetyPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class StandingOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class OrderItemFulfillment(str, Enum):
    PLANNED = "PLANNED"
    ALLOCATED = "ALLOCATED"
    SHORTED = "SHORTED"
    DELIVERED = "DELIVERED"
    CREDITED = "CREDITED"


class DeliveryRouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryStopOutcome(str, Enum):
    SCHEDULED = "SCHEDULED"
    INCLUDED = "INCLUDED"
    SKIPPED = "SKIPPED"
    DELIVERED = "DELIVERED"


class SpoilageCreditStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PricingVariant(str, Enum):
    ORIGINAL_PAPER = "ORIGINAL_PAPER"
    POST_HARVEST_PRICING = "POST_HARVEST_PRICING"


class SurplusListingStatus(str, Enum):
    LISTED = "LISTED"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"


# --- Entities carrying the standard common fields (id, created_at,
# --- updated_at, version) per PRD §2.4 ---


class Customer(TypedDict):
    id: str
    business_name: str
    contact_email: str
    delivery_zone: str
    credit_balance_cents: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Variety(TypedDict):
    id: str
    name: str
    crop_category: str
    days_to_harvest: int
    expected_yield_grams_per_tray: int
    listed_price_cents_per_kg: int
    stage: str
    min_order_grams: int
    created_at: str
    updated_at: str
    version: int


class VarietyTrial(TypedDict):
    id: str
    variety_id: str
    sow_date: str
    chef_panel_size: int
    avg_flavor_score: Optional[float]
    yield_score: float
    decision: str
    created_at: str
    updated_at: str
    version: int


class SeedLot(TypedDict):
    id: str
    variety_id: str
    supplier_name: str
    lot_code: str
    received_date: str
    seeds_on_hand_grams: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GerminationTest(TypedDict):
    id: str
    seed_lot_id: str
    seeds_sown_count: int
    germinated_count: Optional[int]
    germination_rate: Optional[float]
    result: str
    created_at: str
    updated_at: str
    version: int


class CropPlan(TypedDict):
    id: str
    variety_id: str
    planned_sow_date: str
    planned_tray_count: int
    seed_grams_required: int
    status: str
    base_harvest_kg: float
    sown_tray_count: int
    created_at: str
    updated_at: str
    version: int


class TrayBatch(TypedDict):
    id: str
    crop_plan_id: str
    seed_lot_id: str
    tray_count: int
    sown_at: str
    expected_harvest_date: str
    status: str
    harvested_kg: float
    created_at: str
    updated_at: str
    version: int


class FoodSafetyPlan(TypedDict):
    id: str
    plan_code: str
    water_test_current: bool
    sanitation_sop_version: str
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StandingOrder(TypedDict):
    id: str
    customer_id: str
    effective_week_start: str
    change_cutoff_day: int
    status: str
    weekly_subtotal_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderItem(TypedDict):
    id: str
    standing_order_id: str
    variety_id: str
    qty_kg: float
    unit_price_cents_per_kg: int
    line_extension_cents: int
    fulfillment: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict):
    id: str
    route_code: str
    service_date: str
    min_stop_subtotal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryStop(TypedDict):
    id: str
    route_id: str
    customer_id: str
    standing_order_id: str
    stop_subtotal_cents: Optional[int]
    outcome: str
    created_at: str
    updated_at: str
    version: int


class SpoilageCredit(TypedDict):
    id: str
    delivery_stop_id: str
    order_item_id: str
    credit_qty_kg: float
    pricing_variant: str
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SurplusListing(TypedDict):
    id: str
    variety_id: str
    tray_batch_id: str
    qty_kg: float
    market_price_cents_per_kg: int
    market_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only record (PRD §2.4): carries ONLY id + created_at ---


class SanitationLog(TypedDict):
    id: str
    harvest_batch_id: str
    surface_swab_passed: bool
    wash_water_ppm: int
    logged_by: str
    created_at: str
