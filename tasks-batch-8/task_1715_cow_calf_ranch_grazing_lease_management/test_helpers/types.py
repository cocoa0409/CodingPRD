"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    RANCH_MANAGER = "RanchManager"
    RANGE_MANAGER = "RangeManager"
    HERD_MANAGER = "HerdManager"
    SALES_AGENT = "SalesAgent"


class DroughtPosture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    ALERT = "ALERT"
    CRITICAL = "CRITICAL"


class PastureCondition(str, Enum):
    GRAZEABLE = "GRAZEABLE"
    RESTING = "RESTING"
    CLOSED = "CLOSED"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class HerdGroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DESTOCKING = "DESTOCKING"
    LIQUIDATED = "LIQUIDATED"


class AnimalClass(str, Enum):
    MATURE_COW = "MATURE_COW"
    REPLACEMENT_HEIFER = "REPLACEMENT_HEIFER"
    GROWING = "GROWING"


class SeasonStatus(str, Enum):
    PLANNED = "PLANNED"
    BREEDING = "BREEDING"
    GESTATION = "GESTATION"
    PREG_CHECK = "PREG_CHECK"
    CLOSED = "CLOSED"


class BseStatus(str, Enum):
    UNTESTED = "UNTESTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class BullLifeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    CULLED = "CULLED"
    DEAD = "DEAD"


class TurnoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    TURNED_IN = "TURNED_IN"
    REMOVED = "REMOVED"
    CANCELLED = "CANCELLED"


class PregCheckStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class WeanStatus(str, Enum):
    UNWEANED = "UNWEANED"
    WEANED = "WEANED"


class PreconStatus(str, Enum):
    NONE = "NONE"
    ENROLLED = "ENROLLED"
    CERTIFIED = "CERTIFIED"


class CropLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class SaleLotStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    CONTRACTED = "CONTRACTED"
    DELIVERED = "DELIVERED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SHORTENED = "SHORTENED"
    CANCELLED = "CANCELLED"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class DestockOrderStatus(str, Enum):
    OPEN = "OPEN"
    COMPLIANT = "COMPLIANT"
    WAIVED = "WAIVED"
    EXPIRED = "EXPIRED"


class Ranch(TypedDict):
    id: str
    name: str
    hq_state: str
    destock_grace_days: int
    drought_posture: str
    ranch_production_pct: float
    assessment_seq: int
    created_at: str
    updated_at: str
    version: int


class Pasture(TypedDict):
    id: str
    ranch_id: str
    name: str
    acreage: int
    tenure: str
    forage_type: str
    base_capacity_aum: int
    min_rest_days: int
    effective_capacity_aum: float
    committed_aum: float
    consumed_total_aum: float
    available_aum: float
    resting_until: Optional[str]
    closed_flag: bool
    condition_status: str
    created_at: str
    updated_at: str
    version: int


class GrazingLease(TypedDict):
    id: str
    ranch_id: str
    pasture_id: str
    lessor_name: str
    start_date: str
    end_date: str
    aum_allotment: int
    rate_per_aum_cents: int
    minimum_commit_aum: int
    overage_tier1_cap_aum: int
    overage_tier1_rate_cents: int
    overage_tier2_rate_cents: int
    settlement_basis: str
    lease_status: str
    created_at: str
    updated_at: str
    version: int


class LeaseStatement(TypedDict):
    id: str
    lease_id: str
    ranch_id: str
    period_year: int
    actual_aum_used: float
    base_charge_cents: float
    overage_charge_cents: float
    total_due_cents: float
    recorded_by_user_id: str
    approved_by_user_id: Optional[str]
    statement_status: str
    created_at: str
    updated_at: str
    version: int


class HerdGroup(TypedDict):
    id: str
    ranch_id: str
    group_name: str
    animal_class: str
    head_count: int
    avg_weight_lbs: int
    marked_open_head: int
    retained_from_crop_id: Optional[str]
    group_status: str
    created_at: str
    updated_at: str
    version: int


class BreedingSeason(TypedDict):
    id: str
    ranch_id: str
    herd_group_id: str
    season_year: int
    planned_turnout_date: str
    planned_removal_date: str
    exposed_head_count: int
    required_bull_count: int
    season_status: str
    created_at: str
    updated_at: str
    version: int


class Bull(TypedDict):
    id: str
    ranch_id: str
    tag: str
    breed: str
    birth_year: int
    last_bse_date: Optional[str]
    last_bse_result: Optional[str]
    scrotal_cm: Optional[float]
    bse_status: str
    life_status: str
    created_at: str
    updated_at: str
    version: int


class BullTurnout(TypedDict):
    id: str
    bull_id: str
    breeding_season_id: str
    ranch_id: str
    turnout_date: str
    planned_removal_date: str
    actual_removal_date: Optional[str]
    turnout_status: str
    created_at: str
    updated_at: str
    version: int


class PregCheck(TypedDict):
    id: str
    breeding_season_id: str
    ranch_id: str
    check_date: str
    exposed_head_count: int
    pregnant_count: Optional[int]
    open_count: Optional[int]
    dead_count: Optional[int]
    pregnancy_rate_pct: Optional[float]
    check_status: str
    created_at: str
    updated_at: str
    version: int


class CalfCrop(TypedDict):
    id: str
    breeding_season_id: str
    ranch_id: str
    crop_year: int
    steer_head: int
    heifer_head: int
    weaning_date: Optional[str]
    avg_wean_weight_lbs: Optional[float]
    avg_wean_age_days: Optional[int]
    avg_birth_weight_lbs: Optional[float]
    avg_dam_age_years: Optional[int]
    adj205_age_only_lbs: Optional[float]
    adj205_dam_adjusted_lbs: Optional[float]
    vaccine_round_1_date: Optional[str]
    vaccine_round_2_date: Optional[str]
    retained_heifer_head: int
    death_loss_steer_head: int
    death_loss_heifer_head: int
    marketed_steer_head: int
    marketed_heifer_head: int
    reserved_steer_head: int
    reserved_heifer_head: int
    available_steer_head: int
    available_heifer_head: int
    wean_status: str
    precon_status: str
    lifecycle_status: str
    created_at: str
    updated_at: str
    version: int


class SaleLot(TypedDict):
    id: str
    calf_crop_id: str
    ranch_id: str
    lot_class: str
    head_count: int
    base_price_cents_per_cwt: float
    slide_cents_per_lb: float
    base_weight_lbs: float
    shrink_pct: float
    precon_claim: str
    freight_cents_per_head: int
    commission_pct: float
    buyer_name: Optional[str]
    delivered_avg_weight_lbs: Optional[float]
    pay_weight_lbs: Optional[float]
    final_price_cents_per_cwt: Optional[float]
    per_head_gross_cents: Optional[float]
    gross_cents: Optional[float]
    commission_cents: Optional[float]
    freight_cents: Optional[int]
    net_settlement_cents: Optional[float]
    relist_count: int
    sold_by_user_id: str
    settled_by_user_id: Optional[str]
    lot_status: str
    created_at: str
    updated_at: str
    version: int


class GrazingAssignment(TypedDict):
    id: str
    pasture_id: str
    herd_group_id: str
    ranch_id: str
    start_date: str
    planned_end_date: str
    grazing_days: int
    au_factor: float
    daily_demand_aum: float
    reserved_aum: float
    consumed_aum: Optional[float]
    actual_end_date: Optional[str]
    assignment_status: str
    created_at: str
    updated_at: str
    version: int


class SupplementProgram(TypedDict):
    id: str
    herd_group_id: str
    ranch_id: str
    program_type: str
    start_date: str
    end_date: str
    feed_rate_oz_per_head_day: float
    cost_cents_per_ton: int
    delivered_lbs_total: float
    cost_to_date_cents: float
    projected_consumption_lbs: float
    program_status: str
    created_at: str
    updated_at: str
    version: int


class PastureMeasurement(TypedDict):
    pasture_id: str
    production_pct_of_normal: float


class DroughtAssessment(TypedDict):
    id: str
    ranch_id: str
    assessment_date: str
    pasture_measurements: List[Dict[str, Any]]
    ranch_production_pct: float
    monthly_supply_aum: float
    monthly_demand_aum: float
    deficit_aum_per_30d: float
    resulting_posture: str
    assessment_status: str
    created_at: str
    updated_at: str
    version: int


class DestockOrder(TypedDict):
    id: str
    ranch_id: str
    drought_assessment_id: str
    required_reduction_head: int
    received_reduction_head: int
    deadline_date: str
    waiver_note: Optional[str]
    order_status: str
    created_at: str
    updated_at: str
    version: int
