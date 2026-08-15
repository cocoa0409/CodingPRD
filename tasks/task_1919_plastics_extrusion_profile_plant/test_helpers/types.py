"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    PROCESS_ENGINEER = "ProcessEngineer"
    LINE_OPERATOR = "LineOperator"
    QUALITY_INSPECTOR = "QualityInspector"
    SALES_ENGINEER = "SalesEngineer"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class ResinIndexBasis(str, Enum):
    MONTHLY_AVG = "MONTHLY_AVG"
    SHIPMENT_DATE = "SHIPMENT_DATE"


class DieStatus(str, Enum):
    DRAFT = "DRAFT"
    TRIAL = "TRIAL"
    QUALIFIED = "QUALIFIED"
    IN_SERVICE = "IN_SERVICE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class AmortizationMode(str, Enum):
    PER_METER = "PER_METER"
    PER_KG = "PER_KG"


class LineStatus(str, Enum):
    IDLE = "IDLE"
    SETUP = "SETUP"
    RUNNING = "RUNNING"
    DOWN = "DOWN"


class LotKind(str, Enum):
    VIRGIN = "VIRGIN"
    REGRIND = "REGRIND"
    COLORANT = "COLORANT"


class ColorFamily(str, Enum):
    NATURAL = "NATURAL"
    WHITE = "WHITE"
    YELLOW = "YELLOW"
    RED = "RED"
    BLUE = "BLUE"
    GREEN = "GREEN"
    BROWN = "BROWN"
    BLACK = "BLACK"


class ResinLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QC_PASSED = "QC_PASSED"
    QC_REJECTED = "QC_REJECTED"
    DEPLETED = "DEPLETED"


class BlendBatchStatus(str, Enum):
    BLENDED = "BLENDED"
    QC_RELEASED = "QC_RELEASED"
    CONSUMED = "CONSUMED"
    QUARANTINED = "QUARANTINED"


class WorkOrderStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    HOLD = "HOLD"
    COMPLETED = "COMPLETED"


class HoldOrigin(str, Enum):
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"


class PurgeGrade(str, Enum):
    STANDARD = "STANDARD"
    HIGH_EFFICIENCY = "HIGH_EFFICIENCY"


class TransitionClass(str, Enum):
    SAME_RESIN_SAME_COLOR = "SAME_RESIN_SAME_COLOR"
    SAME_RESIN_LIGHT_TO_DARK = "SAME_RESIN_LIGHT_TO_DARK"
    SAME_RESIN_DARK_TO_LIGHT = "SAME_RESIN_DARK_TO_LIGHT"
    RESIN_CHANGE = "RESIN_CHANGE"


# --- Entities carrying the full common-field set (PRD §2.4) ---


class Customer(TypedDict, total=False):
    id: str
    name: str
    resin_index_basis: str
    credit_limit_cents: int
    status: str
    open_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class Profile(TypedDict, total=False):
    id: str
    customer_id: str
    profile_code: str
    critical_dimensions: List[dict]
    spc_subgroup_size: int
    sample_every_m: int
    resin_content_kg_per_m: float
    min_line_speed_mpm: float
    max_line_speed_mpm: float
    created_at: str
    updated_at: str
    version: int


class Die(TypedDict, total=False):
    id: str
    profile_id: str
    die_code: str
    tooling_cost_cents: int
    committed_length_m: float
    committed_weight_kg: float
    amortization_mode: str
    buffer_hours: int
    min_screw_mm: float
    max_screw_mm: float
    amort_rate_cents_per_m: Optional[float]
    amort_rate_cents_per_kg: Optional[float]
    amortized_cents: int
    remaining_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExtrusionLine(TypedDict, total=False):
    id: str
    line_code: str
    screw_diameter_mm: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ResinLot(TypedDict, total=False):
    id: str
    lot_kind: str
    resin_type: str
    color_family: str
    received_kg: float
    supplier_lot_ref: Optional[str]
    consumed_kg: float
    available_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Formulation(TypedDict, total=False):
    id: str
    profile_id: str
    formula_code: str
    base_resin_type: str
    color_family: str
    let_down_ratio: float
    max_regrind_pct: float
    created_at: str
    updated_at: str
    version: int


class BlendBatch(TypedDict, total=False):
    id: str
    formulation_id: str
    virgin_lot_id: str
    regrind_lot_id: Optional[str]
    colorant_lot_id: str
    target_batch_kg: float
    colorant_kg: float
    regrind_kg: float
    virgin_kg: float
    actual_regrind_pct: float
    pre_quarantine_status: Optional[str]
    last_qc_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    customer_id: str
    profile_id: str
    formulation_id: str
    die_id: str
    ordered_length_m: float
    cut_length_mm: int
    pieces_per_bundle: int
    base_unit_price_cents_per_m: float
    quote_month: str
    quote_index_cents_per_kg: float
    pass_through_adj_cents_per_m: float
    current_unit_price_cents_per_m: float
    produced_good_length_m: float
    status: str
    billing_status: str
    billed_length_m: Optional[float]
    invoice_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LineAssignment(TypedDict, total=False):
    id: str
    work_order_id: str
    die_id: str
    line_id: str
    planned_start: str
    planned_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    assignment_id: str
    batch_id: str
    line_speed_mpm: float
    status: str
    hold_origin: Optional[str]
    held_by_user_id: Optional[str]
    samples_posted: int
    good_length_mm: Optional[int]
    good_weight_kg: Optional[float]
    trim_scrap_kg: Optional[float]
    regrind_lot_id: Optional[str]
    remnant_mm: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ResinIndexPoint(TypedDict, total=False):
    id: str
    month: str
    index_cents_per_kg: float
    created_at: str
    updated_at: str
    version: int


# --- Immutable record kinds (PRD §2.4: only id + created_at) ---


class SPCSample(TypedDict, total=False):
    id: str
    run_id: str
    dimension_name: str
    measurements: List[float]
    xbar_mm: float
    range_mm: float
    ooc: bool
    spec_violations: int
    created_at: str


class CutBundle(TypedDict, total=False):
    id: str
    run_id: str
    bundle_seq: int
    pieces: int
    partial: bool
    total_length_mm: int
    created_at: str


class PurgeEvent(TypedDict, total=False):
    id: str
    line_id: str
    from_resin_type: str
    to_resin_type: str
    from_color_family: str
    to_color_family: str
    purge_grade: str
    transition_class: str
    scrap_kg: float
    created_at: str
