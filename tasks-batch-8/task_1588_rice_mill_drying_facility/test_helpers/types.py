"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class SeasonStatus(str, Enum):
    SETUP = "SETUP"
    INTAKE_OPEN = "INTAKE_OPEN"
    INTAKE_CLOSED = "INTAKE_CLOSED"
    SETTLEMENT_REVIEW = "SETTLEMENT_REVIEW"
    SETTLED = "SETTLED"


class ContractStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    DEFAULTED = "DEFAULTED"


class BinStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FUMIGATING = "FUMIGATING"
    AERATING = "AERATING"


class LotStatus(str, Enum):
    WEIGHED = "WEIGHED"
    GRADED = "GRADED"
    BINNED = "BINNED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class DryingRunStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MillRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROCESS = "IN_PROCESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class PackagingRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ByproductOrderStatus(str, Enum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class FumigationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AERATING = "AERATING"
    CLEARED = "CLEARED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROVISIONAL_ISSUED = "PROVISIONAL_ISSUED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class Variety(str, Enum):
    LONG_GRAIN = "LONG_GRAIN"
    MEDIUM_GRAIN = "MEDIUM_GRAIN"


class LotSource(str, Enum):
    CONTRACT = "CONTRACT"
    SPOT = "SPOT"


class Grade(str, Enum):
    US_NO_1 = "US_NO_1"
    US_NO_2 = "US_NO_2"
    US_NO_3 = "US_NO_3"
    US_NO_4 = "US_NO_4"
    US_NO_5 = "US_NO_5"
    SAMPLE = "SAMPLE"


class ByproductProduct(str, Enum):
    BRAN = "BRAN"
    HULL = "HULL"
    BROKEN = "BROKEN"
    BREWERS = "BREWERS"


class PackagingLine(str, Enum):
    LINE_1 = "LINE_1"
    LINE_2 = "LINE_2"


class HoldTargetType(str, Enum):
    BIN = "BIN"
    LOT = "LOT"


class UserRole(str, Enum):
    MILL_ADMIN = "MillAdmin"
    MERCHANDISER = "Merchandiser"
    SCALE_OPERATOR = "ScaleOperator"
    QUALITY_LAB_TECH = "QualityLabTech"
    DRYER_OPERATOR = "DryerOperator"
    MILL_SUPERVISOR = "MillSupervisor"
    SETTLEMENT_CLERK = "SettlementClerk"
    GROWER_REP = "GrowerRep"
    SAFETY_OFFICER = "SafetyOfficer"
    FUMIGATION_TECH = "FumigationTech"


# All twelve resource types carry id + created_at + updated_at + version (PRD §2.5).


class HarvestSeason(TypedDict, total=False):
    id: str
    name: str
    intake_start_date: str
    intake_end_date: str
    spot_daily_cap: int
    current_clock_iso: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Grower(TypedDict, total=False):
    id: str
    season_id: str
    farm_code: str
    legal_name: str
    advance_issued_cents: int
    advance_outstanding_cents: int
    cumulative_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliveryContract(TypedDict, total=False):
    id: str
    season_id: str
    grower_id: str
    variety: str
    contracted_cwt: float
    base_price_cents_per_cwt: int
    grade_adjustments: dict
    delivery_count: int
    fulfilled_cwt: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Bin(TypedDict, total=False):
    id: str
    season_id: str
    bin_code: str
    capacity_cwt: float
    variety_lock: Optional[str]
    stock_cwt: float
    reserved_cwt: float
    available_cwt: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PaddyLot(TypedDict, total=False):
    id: str
    season_id: str
    grower_id: str
    contract_id: Optional[str]
    bin_id: Optional[str]
    drying_run_id: Optional[str]
    settlement_id: Optional[str]
    variety: str
    source: str
    spot_price_cents_per_cwt: Optional[int]
    scheduled_date: str
    gross_weight_lbs: int
    tare_weight_lbs: int
    net_wet_cwt: float
    moisture_pct_handheld: float
    moisture_pct_official: Optional[float]
    provisional_dry_weight_cwt: float
    dry_weight_cwt: Optional[float]
    moisture_shrink_cwt: Optional[float]
    handling_loss_cwt: Optional[float]
    foreign_matter_pct: Optional[float]
    damage_pct: Optional[float]
    broken_pct: Optional[float]
    grade_score: Optional[float]
    grade: Optional[str]
    drying_charge_cents: Optional[int]
    price_cents_per_cwt: Optional[int]
    line_value_cents: Optional[int]
    graded_date: Optional[str]
    reject_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DryingRun(TypedDict, total=False):
    id: str
    season_id: str
    destination_bin_id: str
    lot_ids: List[str]
    fuel_cost_cents: int
    expected_output_cwt: float
    actual_output_cwt: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class MillRun(TypedDict, total=False):
    id: str
    season_id: str
    input_bin_id: str
    variety: str
    input_cwt: float
    est_head_cwt: Optional[float]
    est_broken_cwt: Optional[float]
    est_brewers_cwt: Optional[float]
    est_bran_cwt: Optional[float]
    est_hull_cwt: Optional[float]
    est_loss_cwt: Optional[float]
    act_head_cwt: Optional[float]
    act_broken_cwt: Optional[float]
    act_brewers_cwt: Optional[float]
    act_bran_cwt: Optional[float]
    act_hull_cwt: Optional[float]
    act_loss_cwt: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PackagingRun(TypedDict, total=False):
    id: str
    season_id: str
    line_id: str
    brand_label: str
    package_size_kg: float
    units_planned: int
    units_produced: Optional[int]
    head_rice_consumed_cwt: Optional[float]
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ByproductSaleOrder(TypedDict, total=False):
    id: str
    season_id: str
    product: str
    quantity_cwt: float
    price_cents_per_cwt: int
    buyer_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FumigationEvent(TypedDict, total=False):
    id: str
    season_id: str
    bin_id: str
    fumigant_code: str
    applicator_license: str
    started_at: str
    exposure_hours: int
    aeration_hours: int
    exposure_ends_at: str
    clearance_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FoodSafetyHold(TypedDict, total=False):
    id: str
    season_id: str
    target_type: str
    target_id: str
    reason_code: str
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    season_id: str
    grower_id: str
    period_start_date: str
    period_end_date: str
    lot_ids: List[str]
    created_by_user_id: str
    provisional_gross_cents: int
    provisional_drying_cents: int
    provisional_checkoff_cents: int
    provisional_advance_repay_cents: int
    provisional_net_cents: int
    final_gross_cents: Optional[int]
    final_drying_cents: Optional[int]
    final_checkoff_cents: Optional[int]
    final_advance_repay_cents: Optional[int]
    final_net_cents: Optional[int]
    dispute_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
