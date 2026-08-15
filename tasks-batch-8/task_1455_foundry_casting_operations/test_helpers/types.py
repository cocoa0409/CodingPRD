"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    FOUNDRY_ADMIN = "FoundryAdmin"
    PATTERN_MAKER = "PatternMaker"
    MELT_SUPERVISOR = "MeltSupervisor"
    SPECTROGRAPHER = "Spectrographer"
    LINE_OPERATOR = "LineOperator"
    QUALITY_INSPECTOR = "QualityInspector"
    WARRANTY_MANAGER = "WarrantyManager"
    CUSTOMER = "Customer"


class FoundryPosture(str, Enum):
    OPEN = "OPEN"
    CURTAILED = "CURTAILED"
    EMBARGO = "EMBARGO"


class PatternStatus(str, Enum):
    DRAFT = "DRAFT"
    QUALIFICATION = "QUALIFICATION"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ShrinkClass(str, Enum):
    FERROUS = "FERROUS"
    ALUMINUM = "ALUMINUM"


class MoldProcess(str, Enum):
    SAND = "SAND"
    INVESTMENT = "INVESTMENT"


class OrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EquipmentKind(str, Enum):
    FURNACE = "FURNACE"
    MOLDING_LINE = "MOLDING_LINE"


class HeatStatus(str, Enum):
    CHARGING = "CHARGING"
    SAMPLED = "SAMPLED"
    CERTIFIED = "CERTIFIED"
    TAPPED = "TAPPED"
    POURED_OUT = "POURED_OUT"


class PourSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class MoldStatus(str, Enum):
    ASSEMBLED = "ASSEMBLED"
    POURED = "POURED"
    COOLED = "COOLED"
    SHAKEOUT = "SHAKEOUT"
    CLOSED = "CLOSED"
    SCRAPPED = "SCRAPPED"


class RoutingStatus(str, Enum):
    SHAKEOUT = "SHAKEOUT"
    CLEANING = "CLEANING"
    GRINDING = "GRINDING"
    FINAL_INSPECTION = "FINAL_INSPECTION"
    COMPLETE = "COMPLETE"


class QualityStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    USE_AS_IS = "USE_AS_IS"
    REWORK = "REWORK"
    SCRAPPED = "SCRAPPED"


class DefectType(str, Enum):
    NONE = "NONE"
    POROSITY = "POROSITY"
    SHRINKAGE = "SHRINKAGE"
    INCLUSION = "INCLUSION"
    MISRUN = "MISRUN"
    CRACK = "CRACK"


class Zone(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class Disposition(str, Enum):
    ACCEPT = "ACCEPT"
    USE_AS_IS = "USE_AS_IS"
    REWORK = "REWORK"
    SCRAP = "SCRAP"


class InspectionStatus(str, Enum):
    RECORDED = "RECORDED"
    DISPOSITIONED = "DISPOSITIONED"


class ScrapCode(str, Enum):
    POROSITY = "POROSITY"
    SHRINKAGE = "SHRINKAGE"
    INCLUSION = "INCLUSION"
    MISRUN = "MISRUN"
    CRACK = "CRACK"
    PROCESS = "PROCESS"


class ScrapStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    WEIGHED = "WEIGHED"


class ReturnLotStatus(str, Enum):
    COLLECTED = "COLLECTED"
    ASSAYED = "ASSAYED"
    CONSUMED = "CONSUMED"
    DOWNGRADED = "DOWNGRADED"


class SandBatchStatus(str, Enum):
    MIXED = "MIXED"
    IN_SERVICE = "IN_SERVICE"
    RECLAIMING = "RECLAIMING"
    DISCARDED = "DISCARDED"


class ClaimType(str, Enum):
    DEFECT = "DEFECT"
    MACHINING_SHORTFALL = "MACHINING_SHORTFALL"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class CreditVariant(str, Enum):
    STANDARD = "STANDARD"
    MACHINING_ALLOWANCE = "MACHINING_ALLOWANCE"


class ReviewAction(str, Enum):
    START = "START"
    APPROVE = "APPROVE"
    DENY = "DENY"
    REQUEST_INFO = "REQUEST_INFO"
    RESPOND = "RESPOND"
    APPEAL = "APPEAL"


class ChargeSource(str, Enum):
    VIRGIN = "VIRGIN"
    RETURN_LOT = "RETURN_LOT"


# All resources carry the four system-maintained properties of PRD §2.5
# (id, created_at, updated_at, version).


class Foundry(TypedDict, total=False):
    id: str
    name: str
    sand_available_kg: float
    alloy_available_kg: float
    posture: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    foundry_id: str
    company_name: str
    credit_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class Pattern(TypedDict, total=False):
    id: str
    foundry_id: str
    parent_pattern_id: Optional[str]
    part_number: str
    alloy_shrink_class: str
    mold_process: str
    finish_dimensions_mm: List[float]
    machining_allowance_mm: float
    impressions: int
    pattern_dimensions_mm: List[float]
    qualification_attempts: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict, total=False):
    id: str
    foundry_id: str
    customer_id: str
    pattern_id: str
    quantity: int
    overage_pct: float
    unit_price_cents: int
    machining_allowance_pct: float
    warranty_months: int
    warranty_budget_cents: int
    accepted_count: int
    scrapped_count: int
    pipeline_count: int
    settled_total_cents: int
    fulfilled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict, total=False):
    id: str
    foundry_id: str
    kind: str
    label: str
    daily_tap_capacity_kg: Optional[float]
    daily_minute_capacity: Optional[int]
    cleanup_buffer_minutes: Optional[int]
    maintenance_windows: List[Dict[str, str]]
    created_at: str
    updated_at: str
    version: int


class MeltHeat(TypedDict, total=False):
    id: str
    foundry_id: str
    furnace_id: str
    alloy_grade: str
    chemistry_spec: Dict[str, Any]
    charge_total_kg: float
    charge_composition: Dict[str, float]
    last_sample_reading: Optional[Dict[str, float]]
    last_sample_passed: bool
    certified_by_user_id: Optional[str]
    last_correction_masses: Optional[Dict[str, float]]
    tapped_weight_kg: Optional[float]
    tapped_date: Optional[str]
    remaining_metal_kg: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PourSlot(TypedDict, total=False):
    id: str
    molding_line_id: str
    heat_id: str
    mold_ids: List[str]
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Mold(TypedDict, total=False):
    id: str
    pattern_id: str
    sand_batch_id: str
    order_id: str
    pour_slot_id: Optional[str]
    sand_weight_kg: float
    metal_weight_kg: float
    cooling_hours: int
    poured_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Casting(TypedDict, total=False):
    id: str
    mold_id: str
    order_id: str
    cavity_index: int
    casting_weight_kg: float
    routing_status: str
    quality_status: str
    created_at: str
    updated_at: str
    version: int


class InspectionReport(TypedDict, total=False):
    id: str
    casting_id: str
    porosity_grade: int
    defect_type: str
    zone: str
    disposited_by_user_id: Optional[str]
    disposition: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScrapRecord(TypedDict, total=False):
    id: str
    casting_id: str
    return_lot_id: str
    scrap_code: str
    provisional_weight_kg: float
    actual_weight_kg: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnLot(TypedDict, total=False):
    id: str
    foundry_id: str
    alloy_grade: str
    collected_weight_kg: float
    scrap_credited_kg: float
    consumed_weight_kg: float
    downgraded_weight_kg: float
    remaining_weight_kg: float
    assay_composition: Optional[Dict[str, float]]
    status: str
    created_at: str
    updated_at: str
    version: int


class SandBatch(TypedDict, total=False):
    id: str
    foundry_id: str
    virgin_weight_kg: float
    max_loi_pct: float
    last_loi_pct: Optional[float]
    current_weight_kg: float
    committed_weight_kg: float
    spent_weight_kg: float
    pending_reclaim_kg: float
    discarded_weight_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    order_id: str
    customer_id: str
    claim_type: str
    claim_qty: int
    claimed_amount_cents: int
    freight_cents: int
    appeal_used: bool
    reviewed_by_user_id: Optional[str]
    credit_variant_applied: Optional[str]
    settled_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
