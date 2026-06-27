"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD exactly. Entities that the PRD describes as
append-only event records (StockingEvent, FeedLog, WaterQualityReading) carry
only id and created_at — no updated_at, no version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    FARM_MANAGER = "FarmManager"
    FARM_TECHNICIAN = "FarmTechnician"
    VETERINARIAN = "Veterinarian"
    HARVEST_OPERATOR = "HarvestOperator"
    SALES_AGENT = "SalesAgent"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class TankPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class TankKind(str, Enum):
    TANK = "TANK"
    POND = "POND"
    RACEWAY = "RACEWAY"
    CAGE = "CAGE"


class BroodstockStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class CohortLifecycleStatus(str, Enum):
    STOCKED = "STOCKED"
    GROWING = "GROWING"
    HARVESTING = "HARVESTING"
    HARVESTED = "HARVESTED"


class CohortHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    UNDER_TREATMENT = "UNDER_TREATMENT"
    WITHDRAWAL = "WITHDRAWAL"


class CohortOperationalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ReadingSeverity(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class GradingStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    COMMITTED = "COMMITTED"
    CANCELLED = "CANCELLED"


class TreatmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CLEARED = "CLEARED"


class HarvestStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    BLOCKED = "BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProcessingStatus(str, Enum):
    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class ProductLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class SalesOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class DiscountTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Species(TypedDict):
    id: str
    common_name: str
    code: str
    target_market_weight_g: float
    base_daily_growth_g: float
    default_processing_yield_pct: float
    min_water_temp_c: float
    max_water_temp_c: float
    created_at: str
    updated_at: str
    version: int


class Tank(TypedDict):
    id: str
    name: str
    kind: str
    volume_liters: float
    max_biomass_kg: float
    posture: str
    posture_override: Optional[str]
    current_biomass_kg: float
    created_at: str
    updated_at: str
    version: int


class BroodstockBatch(TypedDict):
    id: str
    species_id: str
    spawned_at: str
    fingerling_count: int
    allocated_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict):
    id: str
    label: str
    species_id: str
    current_tank_id: str
    origin_broodstock_id: Optional[str]
    parent_cohort_id: Optional[str]
    fish_count: int
    stocked_avg_weight_g: float
    stocked_at: str
    cumulative_feed_kg: float
    estimated_biomass_kg: float
    lifecycle_status: str
    health_status: str
    operational_status: str
    withdrawal_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GradingEvent(TypedDict):
    id: str
    source_cohort_id: str
    planned_splits: list
    status: str
    child_cohort_ids: list
    created_at: str
    updated_at: str
    version: int


class HealthTreatment(TypedDict):
    id: str
    cohort_id: str
    tank_id: str
    medication: str
    started_at: str
    duration_days: int
    withdrawal_days: int
    treatment_end_at: str
    withdrawal_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HarvestOrder(TypedDict):
    id: str
    cohort_id: str
    planned_fish_count: int
    scheduled_at: str
    harvested_fish_count: Optional[int]
    harvested_live_weight_kg: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcessingBatch(TypedDict):
    id: str
    harvest_order_id: str
    input_live_weight_kg: float
    estimated_yield_kg: float
    actual_processed_weight_kg: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductLot(TypedDict):
    id: str
    processing_batch_id: str
    species_id: str
    total_weight_kg: float
    reserved_weight_kg: float
    available_weight_kg: float
    shipped_weight_kg: float
    price_per_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    customer_name: str
    discount_tier: str
    order_total: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrderLine(TypedDict):
    id: str
    sales_order_id: str
    product_lot_id: str
    weight_kg: float
    line_subtotal: float
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only event records (common_fields: false -> id + created_at only)
# ---------------------------------------------------------------------------
class StockingEvent(TypedDict):
    id: str
    cohort_id: str
    tank_id: str
    fish_count: int
    stocked_at: str
    expected_harvest_at: str
    created_at: str


class FeedLog(TypedDict):
    id: str
    cohort_id: str
    fed_at: str
    amount_kg: float
    feed_type: str
    created_at: str


class WaterQualityReading(TypedDict):
    id: str
    tank_id: str
    measured_at: str
    dissolved_oxygen_mg_l: float
    ammonia_mg_l: float
    water_temp_c: float
    severity: str
    created_at: str


# ---------------------------------------------------------------------------
# Computed summary read (GET /cohorts/{id}/summary)
# ---------------------------------------------------------------------------
class CohortSummary(TypedDict):
    cohort_id: str
    estimated_biomass_kg: float
    provisional_fcr: float
    cumulative_feed_kg: float
    days_elapsed: int
