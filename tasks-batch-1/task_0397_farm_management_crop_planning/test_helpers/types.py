"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain are full first-class resources carrying
id + created_at + updated_at + version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    FARM_MANAGER = "FarmManager"
    AGRONOMIST = "Agronomist"
    APPLICATOR = "Applicator"
    SALES_AGENT = "SalesAgent"


# ---------------------------------------------------------------------------
# Status enums (PRD §2.9, §3)
# ---------------------------------------------------------------------------
class ParcelStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESTRICTED = "RESTRICTED"
    RETIRED = "RETIRED"


class SoilType(str, Enum):
    CLAY = "CLAY"
    LOAM = "LOAM"
    SAND = "SAND"
    SILT = "SILT"


class Crop(str, Enum):
    CORN = "CORN"
    SOY = "SOY"
    WHEAT = "WHEAT"
    COTTON = "COTTON"
    ALFALFA = "ALFALFA"


class CropPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVISION = "UNDER_REVISION"
    APPROVED = "APPROVED"
    GROWING = "GROWING"
    HARVESTING = "HARVESTING"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class InputCategory(str, Enum):
    SEED = "SEED"
    FERTILIZER = "FERTILIZER"
    CHEMICAL = "CHEMICAL"


class InputUnit(str, Enum):
    LB = "LB"
    GAL = "GAL"
    SEED_UNIT = "SEED_UNIT"
    TON = "TON"


class InputLotStatus(str, Enum):
    OPEN = "OPEN"
    DEPLETED = "DEPLETED"


class ApplicationRecordStatus(str, Enum):
    LOGGED = "LOGGED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class ComplianceRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class PlantingEventStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class HarvestEventStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class QualityStatus(str, Enum):
    UNGRADED = "UNGRADED"
    GRADE_A = "GRADE_A"
    GRADE_B = "GRADE_B"
    REJECTED = "REJECTED"


class SaleStatus(str, Enum):
    IN_INVENTORY = "IN_INVENTORY"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    FULLY_COMMITTED = "FULLY_COMMITTED"
    SHIPPED = "SHIPPED"


class SaleContractStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class EquipmentKind(str, Enum):
    TRACTOR = "TRACTOR"
    COMBINE = "COMBINE"
    SPRAYER = "SPRAYER"
    PLANTER = "PLANTER"


class EquipmentAssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DOWN = "DOWN"


class EquipmentUsageStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class IrrigationEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 — every entity carries id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Parcel(TypedDict):
    id: str
    name: str
    acreage: float
    soil_type: str
    status: str
    reentry_blocked_until: Optional[str]
    active_crop_plan_count: int
    created_at: str
    updated_at: str
    version: int


class CropPlan(TypedDict):
    id: str
    parcel_id: str
    crop: str
    season_year: int
    planned_acres: float
    budget_input_cost: float
    budget_labor_cost: float
    budget_equipment_cost: float
    status: str
    revision_count: int
    planted_acres: float
    harvested_acres: float
    actual_input_cost: float
    actual_labor_cost: float
    actual_equipment_cost: float
    provisional_cost_per_acre: float
    final_cost_per_acre: Optional[float]
    total_yield_units: float
    created_at: str
    updated_at: str
    version: int


class InputProduct(TypedDict):
    id: str
    name: str
    category: str
    unit: str
    unit_cost: float
    restricted_use: bool
    reentry_interval_hours: int
    preharvest_interval_days: int
    max_seasonal_rate_per_acre: Optional[float]
    created_at: str
    updated_at: str
    version: int


class InputLot(TypedDict):
    id: str
    input_product_id: str
    lot_code: str
    quantity_received: float
    quantity_remaining: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ApplicationRecord(TypedDict):
    id: str
    crop_plan_id: str
    input_product_id: str
    applicator_user_id: str
    rate_per_acre: float
    acres_treated: float
    quantity_used: float
    applied_cost: float
    applied_at: Optional[str]
    status: str
    is_restricted: bool
    reentry_clear_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceRecord(TypedDict):
    id: str
    application_record_id: str
    crop_plan_id: str
    applicator_user_id: str
    reentry_interval_hours: int
    preharvest_interval_days: int
    reentry_clear_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlantingEvent(TypedDict):
    id: str
    crop_plan_id: str
    input_lot_id: str
    acres_planted: float
    seed_rate_per_acre: float
    seed_units_used: float
    status: str
    created_at: str
    updated_at: str
    version: int


class HarvestEvent(TypedDict):
    id: str
    crop_plan_id: str
    acres_harvested: float
    gross_quantity: float
    moisture_pct: float
    net_quantity: float
    status: str
    created_at: str
    updated_at: str
    version: int


class HarvestLot(TypedDict):
    id: str
    harvest_event_id: str
    crop_plan_id: str
    quantity: float
    quantity_committed: float
    quality_status: str
    sale_status: str
    committed_contract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SaleContract(TypedDict):
    id: str
    crop: str
    buyer_name: str
    contracted_quantity: float
    min_quality: str
    price_per_unit: float
    committed_quantity: float
    contract_value: float
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentAsset(TypedDict):
    id: str
    name: str
    kind: str
    hourly_cost: float
    status: str
    total_logged_hours: float
    created_at: str
    updated_at: str
    version: int


class EquipmentUsage(TypedDict):
    id: str
    equipment_asset_id: str
    crop_plan_id: str
    window_start: str
    window_end: str
    hours: float
    usage_cost: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LaborEntry(TypedDict):
    id: str
    crop_plan_id: str
    worker_name: str
    hours: float
    hourly_rate: float
    labor_cost: float
    created_at: str
    updated_at: str
    version: int


class IrrigationEvent(TypedDict):
    id: str
    parcel_id: str
    window_start: str
    window_end: str
    inches_applied: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicator(TypedDict):
    id: str
    full_name: str
    license_no: str
    certified: bool
    created_at: str
    updated_at: str
    version: int
