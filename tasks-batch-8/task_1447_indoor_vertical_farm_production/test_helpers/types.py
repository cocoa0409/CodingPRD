"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    FARM_MANAGER = "FarmManager"
    GROWER = "Grower"
    SANITATION_LEAD = "SanitationLead"
    QUALITY_ASSURANCE = "QualityAssurance"
    CONTRACTS_MANAGER = "ContractsManager"
    LABOR_PLANNER = "LaborPlanner"
    WORKER = "Worker"


class CropStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CropCategory(str, Enum):
    LEAFY_GREEN = "LEAFY_GREEN"
    HERB = "HERB"
    FRUITING = "FRUITING"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class WaterLoopPosture(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    SANITATION_DUE = "SANITATION_DUE"
    SANITATION_IN_PROGRESS = "SANITATION_IN_PROGRESS"
    SANITATION_HOLD = "SANITATION_HOLD"


class RackPosture(str, Enum):
    OPERATING = "OPERATING"
    SANITATION_HOLD = "SANITATION_HOLD"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class TowerStatus(str, Enum):
    IDLE = "IDLE"
    ALLOCATED = "ALLOCATED"


class ProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    SEEDED = "SEEDED"
    GROWING = "GROWING"
    AT_RISK = "AT_RISK"
    HARVEST_READY = "HARVEST_READY"
    HARVESTED = "HARVESTED"
    PACKED = "PACKED"
    FAILED = "FAILED"
    CULLED = "CULLED"


class SafetyStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    CONDEMNED = "CONDEMNED"
    QUARANTINED = "QUARANTINED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class CycleResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"


class ShipmentStatus(str, Enum):
    RESERVED = "RESERVED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class LineStatus(str, Enum):
    RESERVED = "RESERVED"
    PACKED = "PACKED"
    SHORTED = "SHORTED"
    SHIPPED = "SHIPPED"
    RELEASED = "RELEASED"


class CrewRole(str, Enum):
    HARVEST_CREW = "HARVEST_CREW"
    PACK_CREW = "PACK_CREW"
    SANITATION_CREW = "SANITATION_CREW"


class ShiftStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class ScopeType(str, Enum):
    FACILITY = "FACILITY"
    ZONE = "ZONE"


class CauseCategory(str, Enum):
    PATHOGEN = "PATHOGEN"
    EQUIPMENT = "EQUIPMENT"
    NUTRIENT = "NUTRIENT"
    CLIMATE = "CLIMATE"
    HUMAN_ERROR = "HUMAN_ERROR"


class ReportStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    REPLANT_REQUESTED = "REPLANT_REQUESTED"
    CLOSED = "CLOSED"


class ReplantStatus(str, Enum):
    QUEUED = "QUEUED"
    CONVERTED = "CONVERTED"
    DROPPED = "DROPPED"


class Weekday(str, Enum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


# ── Entities (all carry id + created_at + updated_at + version per PRD §2.5,
#    except EnergyMeterReading which carries only id + created_at) ────────────

class Crop(TypedDict, total=False):
    id: str
    crop_code: str
    display_name: str
    category: str
    margin_cents_per_lb: int
    floor_price_cents_per_lb: int
    crop_status: str
    created_at: str
    updated_at: str
    version: int


class GrowRecipe(TypedDict, total=False):
    id: str
    crop_id: str
    light_hours_per_day: int
    light_ppfd_umol: int
    ec_target_ms: float
    ph_target: float
    temp_day_c: float
    temp_night_c: float
    humidity_pct: int
    co2_ppm: int
    days_to_harvest: int
    expected_yield_lb_per_tower: float
    recipe_status: str
    created_at: str
    updated_at: str
    version: int


class WaterLoop(TypedDict, total=False):
    id: str
    loop_code: str
    posture: str
    last_passed_at: Optional[str]
    next_sanitation_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Rack(TypedDict, total=False):
    id: str
    rack_code: str
    water_loop_id: str
    zone: str
    tower_count: int
    occupied_towers: int
    rack_posture: str
    created_at: str
    updated_at: str
    version: int


class Tower(TypedDict, total=False):
    id: str
    rack_id: str
    tower_index: int
    tower_status: str
    created_at: str
    updated_at: str
    version: int


class GrowBatch(TypedDict, total=False):
    id: str
    crop_id: str
    recipe_id: str
    origin_replant_request_id: Optional[str]
    production_status: str
    safety_status: str
    seeded_at: Optional[str]
    germination_rate_pct: Optional[float]
    yield_factor: float
    replant_recommended: bool
    stress_extension_days: int
    projected_harvest_at: Optional[str]
    projected_yield_lb: float
    harvested_at: Optional[str]
    harvested_by_user_id: Optional[str]
    grade_a_lb: Optional[float]
    grade_b_lb: Optional[float]
    cull_lb: Optional[float]
    harvested_total_lb: Optional[float]
    packed_lb: float
    packed_available_lb: float
    reserved_lb: float
    actual_cost_per_pound_cents: Optional[float]
    created_at: str
    updated_at: str
    version: int


class TowerAllocation(TypedDict, total=False):
    id: str
    batch_id: str
    tower_id: str
    occupied_from_at: str
    occupied_to_at: str
    allocation_status: str
    created_at: str
    updated_at: str
    version: int


class SanitationCycle(TypedDict, total=False):
    id: str
    water_loop_id: str
    parent_cycle_id: Optional[str]
    scheduled_start_at: str
    scheduled_end_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    result: Optional[str]
    coliform_cfu: Optional[int]
    result_recorded_by: Optional[str]
    cycle_status: str
    created_at: str
    updated_at: str
    version: int


class RetailContract(TypedDict, total=False):
    id: str
    retailer_name: str
    crop_id: str
    weekly_commitment_lb: int
    price_per_pound_cents: int
    penalty_cents_per_short_lb: int
    fill_rate_threshold: float
    week_start_day: str
    start_date: str
    end_date: str
    contract_status: str
    next_unsettled_week_start: str
    consecutive_short_weeks: int
    week_reserved_lb: float
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    contract_id: str
    ship_date: str
    window_start_at: str
    window_end_at: str
    shipment_status: str
    reserved_lb: float
    packed_lb: float
    shipped_lb: float
    has_shortage: bool
    has_safety_block: bool
    invoice_total_cents: int
    created_at: str
    updated_at: str
    version: int


class ShipmentLine(TypedDict, total=False):
    id: str
    shipment_id: str
    batch_id: str
    reserved_lb: float
    packed_lb: Optional[float]
    shipped_lb: float
    line_status: str
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict, total=False):
    id: str
    full_name: str
    certifications: List[str]
    hourly_rate_cents: int
    scheduled_hours_current_week: float
    created_at: str
    updated_at: str
    version: int


class LaborShift(TypedDict, total=False):
    id: str
    shift_date: str
    role_type: str
    start_at: str
    end_at: str
    headcount_required: int
    headcount_assigned: int
    planned_hourly_rate_cents: int
    projected_labor_cost_cents: int
    overtime_hours: float
    shift_status: str
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    shift_id: str
    worker_id: str
    assignment_status: str
    created_at: str
    updated_at: str
    version: int


# Append-only entity (PRD §2.5): carries ONLY id + created_at — no updated_at,
# no version.
class EnergyMeterReading(TypedDict, total=False):
    id: str
    scope_type: str
    zone: Optional[str]
    period_start_at: str
    period_end_at: str
    kwh_consumed: float
    peak_demand_kw: float
    created_at: str


class FailureReport(TypedDict, total=False):
    id: str
    batch_id: str
    cause_category: str
    lost_lb_estimate: float
    triaged_by_user_id: Optional[str]
    report_status: str
    created_at: str
    updated_at: str
    version: int


class ReplantRequest(TypedDict, total=False):
    id: str
    failure_id: str
    priority_score: float
    towers_needed: int
    replant_status: str
    created_at: str
    updated_at: str
    version: int
