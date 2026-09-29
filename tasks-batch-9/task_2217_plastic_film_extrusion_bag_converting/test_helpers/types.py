"""Domain types for the film extrusion and bag converting API.

Entity TypedDicts, status enums and the role enum, all derived from the PRD.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    BLEND_ENGINEER = "BlendEngineer"
    QUALITY_MANAGER = "QualityManager"
    EXTRUSION_OPERATOR = "ExtrusionOperator"
    PRINT_OPERATOR = "PrintOperator"
    CONVERTING_OPERATOR = "ConvertingOperator"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations used on inputs
# --------------------------------------------------------------------------
class BagStyle(str, Enum):
    FLAT = "FLAT"
    GUSSETED = "GUSSETED"
    BOTTOM_SEAL_LINER = "BOTTOM_SEAL_LINER"


class ProcessType(str, Enum):
    BLOWN = "BLOWN"
    CAST = "CAST"


class MaterialClass(str, Enum):
    VIRGIN_RESIN = "VIRGIN_RESIN"
    ADDITIVE_MASTERBATCH = "ADDITIVE_MASTERBATCH"


class PolymerFamily(str, Enum):
    LDPE = "LDPE"
    LLDPE = "LLDPE"
    HDPE = "HDPE"
    MDPE = "MDPE"
    EVOH = "EVOH"
    TIE = "TIE"


class ComponentKind(str, Enum):
    VIRGIN = "VIRGIN"
    REGRIND = "REGRIND"
    ADDITIVE = "ADDITIVE"


class FoodContactStatus(str, Enum):
    FOOD_CONTACT_ELIGIBLE = "FOOD_CONTACT_ELIGIBLE"
    NON_FOOD_ONLY = "NON_FOOD_ONLY"


class RegrindDirection(str, Enum):
    IN = "IN"
    OUT = "OUT"


class RegrindOriginKind(str, Enum):
    EXTRUSION_SCRAP = "EXTRUSION_SCRAP"
    ROLL_SCRAP = "ROLL_SCRAP"
    LOT_SCRAP = "LOT_SCRAP"
    REINCORPORATION = "REINCORPORATION"
    REVERSAL = "REVERSAL"


class SealTestKind(str, Enum):
    BOTTOM_SEAL = "BOTTOM_SEAL"
    SIDE_SEAL = "SIDE_SEAL"


class PoolPolymerFamily(str, Enum):
    LDPE = "LDPE"
    LLDPE = "LLDPE"
    HDPE = "HDPE"
    MDPE = "MDPE"


class PcrBand(str, Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class BlendRecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ExtrusionRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    HELD = "HELD"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


class FilmRollStatus(str, Enum):
    WOUND = "WOUND"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"
    SCRAPPED = "SCRAPPED"
    QUARANTINED = "QUARANTINED"


class PlateSetStatus(str, Enum):
    NEW = "NEW"
    MOUNTED = "MOUNTED"
    WORN = "WORN"


class PrintJobStatus(str, Enum):
    SETUP = "SETUP"
    PRINTING = "PRINTING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


class RegistrationState(str, Enum):
    REG_PENDING = "REG_PENDING"
    REG_PASS = "REG_PASS"
    REG_FAIL = "REG_FAIL"


class ColorState(str, Enum):
    COLOR_PENDING = "COLOR_PENDING"
    COLOR_PASS = "COLOR_PASS"
    COLOR_FAIL = "COLOR_FAIL"


class BagLotStatus(str, Enum):
    CONVERTING = "CONVERTING"
    TESTING = "TESTING"
    QUALIFIED = "QUALIFIED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"
    PACKED = "PACKED"
    RELEASED = "RELEASED"
    SHIPPED = "SHIPPED"
    QUARANTINED = "QUARANTINED"


class DossierStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class LinePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class GaugeCapabilityState(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    CAPABLE = "CAPABLE"
    MARGINAL = "MARGINAL"
    INCAPABLE = "INCAPABLE"


class SealProvisionalVerdict(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class SealFinalVerdict(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class ClaimConformance(str, Enum):
    PENDING = "PENDING"
    CONFORMING = "CONFORMING"
    OVERSTATED = "OVERSTATED"
    UNDERSTATED = "UNDERSTATED"


# --------------------------------------------------------------------------
# Entity shapes
# Entities carry id, created_at, updated_at and version, except
# RegrindTransaction which is an append-only ledger row and carries only
# id and created_at.
# --------------------------------------------------------------------------
class Product(TypedDict):
    id: str
    product_code: str
    customer_code: str
    bag_style: str
    food_contact_required: bool
    target_gauge_micron: float
    gauge_tolerance_pct: float
    layflat_width_mm: float
    bag_length_mm: float
    gusset_depth_mm: float
    perforation_required: bool
    min_bottom_seal_n_per_15mm: float
    min_strength_index: float
    max_regrind_pct_food: float
    max_regrind_pct_nonfood: float
    declared_recycled_content_pct: float
    assumed_regrind_pcr_pct: float
    bags_per_case: int
    min_partial_case_bags: int
    cases_per_pallet: int
    count_accuracy_tolerance_pct: float
    required_layer_count: int
    created_at: str
    updated_at: str
    version: int


class ResinGrade(TypedDict):
    id: str
    grade_code: str
    material_class: str
    polymer_family: str
    melt_index: float
    density_kg_m3: float
    food_contact_approved: bool
    pcr_content_pct: float
    cost_per_kg: float
    dart_impact_index: float
    haze_index: float
    cof_index: float
    seal_initiation_temp_c: float
    is_barrier: bool
    created_at: str
    updated_at: str
    version: int


class BlendRecipe(TypedDict):
    id: str
    recipe_code: str
    product_id: str
    supersedes_recipe_id: Optional[str]
    process_type: str
    layer_count: int
    components: List[dict]
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    total_weight_pct: float
    regrind_pct: float
    additive_pct: float
    hdpe_pct: float
    dominant_polymer_family: Optional[str]
    barrier_layer_present: bool
    blend_cost_per_kg: float
    blended_density_kg_m3: float
    strength_index: float
    clarity_index: float
    slip_index: float
    virgin_pcr_pct: float
    pcr_band: Optional[str]
    regrind_cap_pct: float
    nominal_recycled_content_pct: float
    food_contact_eligible: bool
    pinned_run_count: int
    supersede_pending: bool
    created_at: str
    updated_at: str
    version: int


class ExtrusionLine(TypedDict):
    id: str
    line_code: str
    process_type: str
    max_layers: int
    min_gauge_micron: float
    max_gauge_micron: float
    max_layflat_mm: float
    purge_buffer_minutes: int
    food_contact_certified: bool
    posture: str
    incapable_run_count: int
    active_hold_count: int
    revoked_dossier_count: int
    created_at: str
    updated_at: str
    version: int


class ExtrusionRun(TypedDict):
    id: str
    run_code: str
    line_id: str
    blend_recipe_id: str
    scheduled_start: str
    scheduled_end: str
    target_output_kg: float
    status: str
    hold_count: int
    hold_reason: Optional[str]
    gauge_readings: List[dict]
    gauge_sample_count: int
    gauge_mean_micron: Optional[float]
    gauge_sd_micron: Optional[float]
    gauge_cv_pct: Optional[float]
    gauge_capability_index: Optional[float]
    gauge_capability_state: str
    layflat_deviation_max_mm: float
    bubble_instability_events: int
    gross_output_kg: Optional[float]
    scrap_kg: Optional[float]
    net_good_kg: Optional[float]
    regrind_consumed_kg: float
    regrind_actual_pct: Optional[float]
    pcr_mass_kg: Optional[float]
    actual_recycled_content_pct: Optional[float]
    recipe_pin_released: bool
    created_at: str
    updated_at: str
    version: int


class FilmRoll(TypedDict):
    id: str
    extrusion_run_id: str
    roll_number: int
    net_kg: float
    layflat_mm: float
    gauge_micron_avg: float
    status: str
    actual_recycled_content_pct: Optional[float]
    release_blocked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegrindPool(TypedDict):
    id: str
    pool_code: str
    food_contact_status: str
    polymer_family: str
    available_kg: float
    cumulative_in_kg: float
    cumulative_out_kg: float
    cumulative_in_pcr_kg: float
    embedded_pcr_pct: float
    generation_count: int
    reincorporation_count: int
    created_at: str
    updated_at: str
    version: int


class RegrindTransaction(TypedDict):
    """Append-only ledger row: carries only id and created_at."""
    id: str
    pool_id: str
    extrusion_run_id: Optional[str]
    reverses_transaction_id: Optional[str]
    direction: str
    origin_kind: str
    origin_ref_id: Optional[str]
    kg: float
    pcr_kg: float
    pool_available_kg_after: float
    reversal_reason: Optional[str]
    recorded_at: str
    created_at: str


class PrintPress(TypedDict):
    id: str
    press_code: str
    cylinder_capacity: int
    max_colors: int
    registration_tolerance_micron: float
    max_delta_e: float
    created_at: str
    updated_at: str
    version: int


class PlateSet(TypedDict):
    id: str
    plate_code: str
    product_id: str
    color_count: int
    mounted_press_id: Optional[str]
    wear_limit_impressions: int
    status: str
    impressions_count: int
    nonconformance_count: int
    created_at: str
    updated_at: str
    version: int


class PrintJob(TypedDict):
    id: str
    job_code: str
    film_roll_id: str
    plate_set_id: str
    press_id: str
    window_start: str
    window_end: str
    cylinders_required: int
    status: str
    registration_state: str
    color_state: str
    registration_drift_micron: Optional[float]
    delta_e_measured: Optional[float]
    setup_attempt_count: int
    printed_kg: Optional[float]
    blocked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BagLot(TypedDict):
    id: str
    lot_code: str
    print_job_id: str
    product_id: str
    bag_count_produced: int
    bag_count_scrapped: int
    bag_count_unpacked: int
    packed_bag_count: int
    packed_case_count: int
    partial_case_bag_count: int
    pallet_count: int
    bag_unit_weight_kg: Optional[float]
    bag_count_theoretical: Optional[int]
    count_accuracy_pct: Optional[float]
    count_accuracy_conforming: bool
    seal_specimens: List[dict]
    seal_provisional_mean_n: Optional[float]
    seal_provisional_verdict: Optional[str]
    seal_final_min_n: Optional[float]
    seal_final_mean_n: Optional[float]
    seal_final_verdict: Optional[str]
    perforation_verified: bool
    gusset_verified: bool
    actual_recycled_content_pct: Optional[float]
    status: str
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceDossier(TypedDict):
    id: str
    dossier_code: str
    bag_lot_id: str
    food_contact_declared: bool
    recycled_content_claim_pct: float
    as_built_recycled_content_pct: Optional[float]
    claim_variance_pct: Optional[float]
    claim_conformance: Optional[str]
    status: str
    issued_by_user_id: Optional[str]
    issued_at: Optional[str]
    revoked_at: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
