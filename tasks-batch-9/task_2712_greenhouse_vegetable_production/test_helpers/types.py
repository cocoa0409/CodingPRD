"""Domain types for the Greenhouse Vegetable Production API.

Status enums, role enum and entity TypedDicts, named exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    GROWER_MANAGER = "GrowerManager"
    IRRIGATION_TECH = "IrrigationTech"
    IPM_SCOUT = "IPMScout"
    IPM_COORDINATOR = "IPMCoordinator"
    HARVEST_SUPERVISOR = "HarvestSupervisor"
    QUALITY_INSPECTOR = "QualityInspector"


class ZoneStatus(str, Enum):
    IDLE = "IDLE"
    PLANTED = "PLANTED"
    HARVESTING = "HARVESTING"
    TURNAROUND = "TURNAROUND"


class IpmPosture(str, Enum):
    NORMAL = "NORMAL"
    SCOUT_ALERT = "SCOUT_ALERT"
    LOCKED = "LOCKED"


class IrrigationPosture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    LOCKED = "LOCKED"


class GlazingType(str, Enum):
    GLASS = "GLASS"
    POLY = "POLY"


class CropType(str, Enum):
    TOMATO = "TOMATO"
    CUCUMBER = "CUCUMBER"
    PEPPER = "PEPPER"


class CropCycleStatus(str, Enum):
    PLANNED = "PLANNED"
    TRANSPLANTED = "TRANSPLANTED"
    PRODUCTION = "PRODUCTION"
    TERMINATION_SCHEDULED = "TERMINATION_SCHEDULED"
    TERMINATED = "TERMINATED"
    ABORTED = "ABORTED"


class Regime(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"


class ClimateStrategyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class FertigationBatchStatus(str, Enum):
    MIXED = "MIXED"
    DELIVERED = "DELIVERED"
    RECONCILED = "RECONCILED"
    DISCARDED = "DISCARDED"


class PestCode(str, Enum):
    WHITEFLY = "WHITEFLY"
    THRIPS = "THRIPS"
    SPIDER_MITE = "SPIDER_MITE"
    APHID = "APHID"


class ThresholdStatus(str, Enum):
    BELOW = "BELOW"
    AT = "AT"
    ABOVE = "ABOVE"


class AgentCode(str, Enum):
    ENCARSIA = "ENCARSIA"
    AMBLYSEIUS = "AMBLYSEIUS"
    APHIDIUS = "APHIDIUS"


class BioControlReleaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class WorkerSkill(str, Enum):
    DELEAF = "DELEAF"
    TRELLIS = "TRELLIS"
    HARVEST = "HARVEST"
    SCOUT = "SCOUT"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TaskType(str, Enum):
    DELEAF = "DELEAF"
    TRELLIS = "TRELLIS"
    HARVEST = "HARVEST"


class LaborTaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class GradingStatus(str, Enum):
    UNGRADED = "UNGRADED"
    GRADED = "GRADED"
    REGRADED = "REGRADED"


class ColdChainStatus(str, Enum):
    AMBIENT = "AMBIENT"
    PRECOOLED = "PRECOOLED"
    COLD_HELD = "COLD_HELD"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class GradeSpec(str, Enum):
    A_ONLY = "A_ONLY"
    A_AND_B = "A_AND_B"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class CommitmentWeekStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CLOSED_FULFILLED = "CLOSED_FULFILLED"
    CLOSED_SHORT = "CLOSED_SHORT"


class AllocationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    REVOKED = "REVOKED"


class Grade(str, Enum):
    A = "A"
    B = "B"


class PostureTargetField(str, Enum):
    IPM_POSTURE = "ipm_posture"
    IRRIGATION_POSTURE = "irrigation_posture"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------


class Zone(TypedDict):
    id: str
    code: str
    area_sqft: int
    glazing_type: str
    has_thermal_screen: bool
    has_supplemental_lighting: bool
    chp_connected: bool
    hive_slot_capacity: int
    labor_budget_usd: float
    status: str
    ipm_posture: str
    irrigation_posture: str
    open_pest_alert_count: int
    drain_alarm_count: int
    hive_slots_used: int
    climate_plan_revision: int
    labor_budget_committed_usd: float
    labor_budget_remaining_usd: float
    reentry_clear_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Variety(TypedDict):
    """A cultivar is immutable: only id and created_at, no updated_at and no version."""

    id: str
    name: str
    crop_type: str
    cycle_length_weeks: int
    first_harvest_week: int
    plant_density_per_sqft: float
    yield_curve_lbs_per_sqft: List[float]
    grade_a_ratio_pct: int
    requires_pollination: bool
    ec_target_ms: float
    created_at: str


class CropCycle(TypedDict):
    id: str
    zone_id: str
    variety_id: str
    transplant_date: str
    plants_transplanted: int
    planned_end_date: str
    first_harvest_allowed_date: str
    status: str
    density_factor: float
    expected_weekly_yield_lbs: List[float]
    baseline_total_yield_lbs: float
    expected_total_yield_lbs: float
    cumulative_harvested_lbs: float
    yield_variance_pct: float
    hive_count_placed: int
    hives_placed_at: Optional[str]
    pollination_strength_index: Optional[float]
    pollination_risk_score: Optional[float]
    pollination_haircut_pct: float
    nutrient_stress_flag: bool
    labor_shortfall_flag: bool
    termination_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClimateStrategy(TypedDict):
    id: str
    zone_id: str
    regime: str
    window_start: str
    window_end: str
    temp_setpoint_c: float
    rh_setpoint_pct: int
    co2_setpoint_ppm: int
    lighting_hours: float
    screen_position_pct: int
    status: str
    window_hours: float
    planned_heat_kwh: float
    planned_light_kwh: float
    planned_co2_kg: float
    projected_energy_cost_usd: float
    gas_consumed_m3: Optional[float]
    chp_generated_kwh: Optional[float]
    grid_import_kwh: Optional[float]
    screen_deployed_hours: Optional[float]
    actuals_recorded_at: Optional[str]
    settled_energy_cost_usd: Optional[float]
    cost_variance_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class FertigationBatch(TypedDict):
    id: str
    zone_id: str
    crop_cycle_id: str
    batch_date: str
    planned_volume_liters: int
    requested_recirculated_liters: int
    reservoir_ec_ms: float
    target_ec_ms: float
    target_ph: float
    n_ppm: int
    k_ppm: int
    ca_ppm: int
    drain_target_pct: int
    status: str
    provisional_blend_ec_ms: float
    recirc_cap_pct: int
    recirculated_liters_applied: int
    fresh_liters_applied: int
    blended_ec_ms: float
    injector_ml: float
    delivered_volume_liters: Optional[float]
    drain_reading_count: int
    cumulative_drain_volume_liters: float
    last_drain_ec_ms: Optional[float]
    drain_fraction_pct: Optional[float]
    drain_alarm: bool
    created_at: str
    updated_at: str
    version: int


class ScoutingObservation(TypedDict):
    """An observation is immutable: only id and created_at, no updated_at and no version."""

    id: str
    zone_id: str
    crop_cycle_id: str
    observed_at: str
    pest_code: str
    plants_inspected: int
    pest_count_per_plant: float
    observed_by_worker_id: str
    action_threshold: float
    threshold_status: str
    release_required: bool
    created_at: str


class BioControlRelease(TypedDict):
    id: str
    zone_id: str
    observation_id: str
    agent_code: str
    planned_release_count: int
    planned_release_date: str
    status: str
    revision_count: int
    requested_by_worker_id: str
    approved_release_count: Optional[int]
    decided_by_worker_id: Optional[str]
    decision_reason: Optional[str]
    released_at: Optional[str]
    actual_release_count: Optional[int]
    reentry_hours: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    full_name: str
    skill: str
    hourly_rate_usd: float
    productivity_index: float
    status: str
    committed_hours: float
    created_at: str
    updated_at: str
    version: int


class LaborTask(TypedDict):
    id: str
    zone_id: str
    crop_cycle_id: str
    worker_id: str
    task_type: str
    window_start: str
    window_end: str
    planned_units: float
    standard_units_per_hour: float
    status: str
    planned_hours: float
    planned_cost_usd: float
    actual_hours: Optional[float]
    actual_units: Optional[float]
    productivity_ratio: Optional[float]
    bonus_usd: Optional[float]
    actual_cost_usd: Optional[float]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HarvestLot(TypedDict):
    id: str
    crop_cycle_id: str
    labor_task_id: Optional[str]
    harvest_date: str
    gross_weight_lbs: float
    grading_status: str
    cold_chain_status: str
    grade_a_lbs: Optional[float]
    grade_b_lbs: Optional[float]
    cull_lbs: Optional[float]
    pack_out_pct: Optional[float]
    allocated_a_lbs: float
    allocated_b_lbs: float
    available_a_lbs: float
    available_b_lbs: float
    regrade_count: int
    pulp_temp_c: Optional[float]
    graded_by_worker_id: Optional[str]
    cold_chain_released_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailProgram(TypedDict):
    id: str
    retailer_name: str
    program_code: str
    grade_spec: str
    weekly_commitment_lbs: float
    price_per_lb_usd: float
    shortfall_penalty_per_lb_usd: float
    priority_rank: int
    status: str
    at_risk_week_count: int
    penalty_accrued_usd: float
    created_at: str
    updated_at: str
    version: int


class CommitmentWeek(TypedDict):
    id: str
    program_id: str
    iso_week: str
    week_start_date: str
    committed_lbs: float
    status: str
    allocated_lbs: float
    shipped_lbs: float
    fill_rate_pct: float
    provisional_shortfall_lbs: float
    provisional_penalty_usd: float
    final_shortfall_lbs: Optional[float]
    final_penalty_usd: Optional[float]
    gross_revenue_usd: Optional[float]
    net_payout_usd: Optional[float]
    shipped_at: Optional[str]
    shipped_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotAllocation(TypedDict):
    id: str
    lot_id: str
    commitment_week_id: str
    grade: str
    allocated_lbs: float
    allocated_at: str
    status: str
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
