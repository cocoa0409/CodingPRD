"""Domain types for the Cutting Tool & Carbide Insert Manufacturing API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them. Every persisted resource in this system carries the four
universal system-managed properties (``id``, ``created_at``, ``updated_at``,
``version``), so every entity TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1 — seven roles, spellings exact) ────────────────────────

class UserRole(str, Enum):
    METALLURGY_ENGINEER = "MetallurgyEngineer"
    GEOMETRY_ENGINEER = "GeometryEngineer"
    COATING_ENGINEER = "CoatingEngineer"
    APPLICATION_ENGINEER = "ApplicationEngineer"
    QUALITY_APPROVER = "QualityApprover"
    PRODUCTION_PLANNER = "ProductionPlanner"
    CUSTOMER = "Customer"


# ─── Status dimensions ──────────────────────────────────────────────────────

class GradeStatus(str, Enum):
    DRAFT = "DRAFT"
    PILOT = "PILOT"
    QUALIFIED = "QUALIFIED"
    RETIRED = "RETIRED"


class BatchStage(str, Enum):
    BLENDED = "BLENDED"
    PRESSED = "PRESSED"
    SINTERED = "SINTERED"
    CONSUMED = "CONSUMED"


class BatchQcStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class GeometryStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"


class CoatingRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class WheelStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DRESSING = "DRESSING"
    EXPIRED = "EXPIRED"


class GrindingRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class ProductReleaseStatus(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    QUALIFICATION = "QUALIFICATION"
    RELEASED = "RELEASED"
    RESTRICTED = "RESTRICTED"
    WITHDRAWN = "WITHDRAWN"


class ProductSupplyStatus(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    MAKE_TO_ORDER = "MAKE_TO_ORDER"
    STOCKED = "STOCKED"


class DossierStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TrialStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"


class TrialVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CustomerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ENGINEERING_REVIEW = "ENGINEERING_REVIEW"
    CONFIRMED = "CONFIRMED"
    ON_HOLD = "ON_HOLD"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class JobStatus(str, Enum):
    RECEIVED = "RECEIVED"
    INSPECTED = "INSPECTED"
    REFURBISHED = "REFURBISHED"
    RETURNED = "RETURNED"
    SCRAPPED = "SCRAPPED"


# ─── Domain enumerations ────────────────────────────────────────────────────

class WorkpieceGroup(str, Enum):
    P = "P"
    M = "M"
    K = "K"
    N = "N"
    S = "S"
    H = "H"


class ApplicationClass(str, Enum):
    ROUGHING = "ROUGHING"
    MEDIUM = "MEDIUM"
    FINISHING = "FINISHING"


class EdgePrep(str, Enum):
    SHARP = "SHARP"
    HONED = "HONED"
    CHAMFERED = "CHAMFERED"
    T_LAND = "T_LAND"


class DepositionType(str, Enum):
    PVD = "PVD"
    CVD = "CVD"


class LayerMaterial(str, Enum):
    TiN = "TiN"
    TiAlN = "TiAlN"
    AlCrN = "AlCrN"
    Al2O3 = "Al2O3"
    TiCN = "TiCN"


class ToolType(str, Enum):
    INSERT = "INSERT"
    SOLID_CARBIDE_ENDMILL = "SOLID_CARBIDE_ENDMILL"
    SOLID_CARBIDE_DRILL = "SOLID_CARBIDE_DRILL"


class OrderClass(str, Enum):
    CATALOG = "CATALOG"
    SPECIAL = "SPECIAL"


class Coolant(str, Enum):
    FLOOD = "FLOOD"
    THROUGH_TOOL = "THROUGH_TOOL"
    DRY = "DRY"


class MachineRigidity(str, Enum):
    RIGID = "RIGID"
    MEDIUM = "MEDIUM"
    WEAK = "WEAK"


class ConfidenceClass(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ToleranceClass(str, Enum):
    IT6 = "IT6"
    IT7 = "IT7"
    IT8 = "IT8"
    OUT_OF_TOLERANCE = "OUT_OF_TOLERANCE"


class CustomerTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    STRATEGIC = "STRATEGIC"


class ChamberId(str, Enum):
    CH1 = "CH1"
    CH2 = "CH2"
    CH3 = "CH3"


class CellId(str, Enum):
    CELL_A = "CELL_A"
    CELL_B = "CELL_B"


# ─── Entities ───────────────────────────────────────────────────────────────

class CarbideGrade(TypedDict):
    id: str
    grade_code: str
    target_workpiece_group: str
    co_binder_pct: float
    wc_grain_um: float
    hardness_hv: int
    trs_mpa: int
    status: str
    revision: int
    qualified_product_count: int
    authored_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class PowderBlendBatch(TypedDict):
    id: str
    grade_id: str
    batch_code: str
    planned_mass_kg: float
    stage: str
    qc_status: str
    pinned_grade_revision: int
    pressed_units: int
    sintered_units: int
    scrap_units: int
    remaining_units: int
    measured_density_gcc: Optional[float]
    measured_hardness_hv: Optional[int]
    yield_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class InsertGeometry(TypedDict):
    id: str
    geometry_code: str
    iso_designation: str
    application_class: str
    chipbreaker_code: str
    rake_angle_deg: float
    nose_radius_mm: float
    max_depth_of_cut_mm: float
    edge_prep: str
    status: str
    revision: int
    created_at: str
    updated_at: str
    version: int


class CoatingRecipe(TypedDict):
    id: str
    recipe_code: str
    deposition_type: str
    layers: List[dict]
    total_thickness_um: float
    adhesion_class: Optional[int]
    is_validated: bool
    revision: int
    created_at: str
    updated_at: str
    version: int


class CoatingRun(TypedDict):
    id: str
    recipe_id: str
    chamber_id: str
    window_start: str
    window_end: str
    loaded_area_cm2: float
    status: str
    pinned_recipe_revision: int
    adhesion_hf_class: Optional[int]
    measured_thickness_um: Optional[float]
    created_at: str
    updated_at: str
    version: int


class GrindingWheel(TypedDict):
    id: str
    wheel_code: str
    spec_code: str
    initial_life_units: int
    consumed_life_units: int
    remaining_life_units: int
    dress_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrindingRun(TypedDict):
    id: str
    wheel_id: str
    product_id: str
    cell_id: str
    window_start: str
    window_end: str
    planned_units: int
    produced_units: int
    scrap_units: int
    measured_diameter_dev_um: Optional[float]
    tolerance_class: Optional[str]
    consumed_life_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ToolProduct(TypedDict):
    id: str
    sku: str
    order_class: str
    grade_id: str
    geometry_id: str
    coating_recipe_id: Optional[str]
    base_catalog_product_id: Optional[str]
    tool_type: str
    list_price_cents: int
    min_order_qty: int
    nominal_length_mm: float
    min_regrind_length_mm: float
    regrind_step_mm: float
    grind_units_per_tool: int
    release_status: str
    supply_status: str
    pinned_grade_revision: Optional[int]
    pinned_geometry_revision: Optional[int]
    pinned_coating_revision: Optional[int]
    engineering_lead_time_days: int
    expedite_eligible: bool
    tool_life_index: Optional[float]
    qualified_workpiece_groups: List[str]
    open_order_units: int
    created_at: str
    updated_at: str
    version: int


class QualificationDossier(TypedDict):
    id: str
    product_id: str
    dossier_code: str
    required_trial_count: int
    status: str
    completed_trial_count: int
    passed_trial_count: int
    composite_score: Optional[float]
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MachiningTrial(TypedDict):
    id: str
    dossier_id: str
    batch_id: str
    trial_code: str
    workpiece_material_code: str
    workpiece_group: str
    units_consumed: int
    cutting_speed_vc: float
    feed_fz: float
    depth_ap: float
    coolant: str
    status: str
    operator_user_id: str
    wear_measurements: Optional[List[dict]]
    measured_surface_ra_um: Optional[float]
    rated_life_min: Optional[float]
    projected_life_min: Optional[float]
    censored: Optional[bool]
    verdict: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    customer_code: str
    name: str
    tier: str
    regrind_credit_cents: int
    reserved_credit_cents: int
    account_status: str
    created_at: str
    updated_at: str
    version: int


class ToolOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    order_code: str
    order_class: str
    quantity: int
    expedite_requested: bool
    status: str
    requires_reconfirmation: bool
    hold_reason: Optional[str]
    per_unit_net_cents: Optional[int]
    total_price_cents: Optional[int]
    promised_lead_time_days: Optional[int]
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReconditionJob(TypedDict):
    id: str
    customer_id: str
    product_id: str
    job_code: str
    units_received: int
    predecessor_job_id: Optional[str]
    regrind_pass_no: int
    reserved_credit_cents: int
    status: str
    units_inspected: Optional[int]
    measured_length_mm: Optional[float]
    measured_corner_wear_um: Optional[float]
    remaining_regrinds: Optional[int]
    life_extension_pct: Optional[float]
    warranted_life_extension_pct: Optional[float]
    scrap_recommended: Optional[bool]
    wheel_id: Optional[str]
    recoat_applied: Optional[bool]
    units_returned: Optional[int]
    rebate_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
