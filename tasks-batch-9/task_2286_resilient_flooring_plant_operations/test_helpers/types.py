"""Domain enumerations and response shapes declared by the PRD.

Every enumerated value listed here is quoted from PRD section 2.11
("Enumerations and Filter Vocabulary"), which states that "Every enumerated
value in this system is an exact uppercase string, and a value outside the
declared set is a shape error (ERR_INVALID_REQUEST, HTTP 400) rather than a
business error."
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """PRD 2.1: the seven role names accepted in X-User-Role."""

    PLANT_ADMIN = "PlantAdmin"
    FORMULATOR = "Formulator"
    TECHNICAL_DIRECTOR = "TechnicalDirector"
    QA_TECHNICIAN = "QaTechnician"
    PRODUCTION_PLANNER = "ProductionPlanner"
    WARRANTY_ADJUSTER = "WarrantyAdjuster"
    DISTRIBUTOR = "Distributor"


class DistributorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RawMaterialCategory(str, Enum):
    VINYL_RESIN = "VINYL_RESIN"
    PLASTICIZER = "PLASTICIZER"
    FILLER = "FILLER"
    STABILIZER = "STABILIZER"


class RawMaterialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    DISCONTINUED = "DISCONTINUED"


class FormulationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class CostBasis(str, Enum):
    LIVE = "LIVE"
    PINNED = "PINNED"


class IndentationResistanceClass(str, Enum):
    CLASS_23_31 = "CLASS_23_31"
    CLASS_33_42 = "CLASS_33_42"
    CLASS_34_43 = "CLASS_34_43"


class LicenseType(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"
    INTERNAL = "INTERNAL"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class PrintFilmStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESTRICTED = "RESTRICTED"
    WITHDRAWN = "WITHDRAWN"


class ConstructionType(str, Enum):
    GLUE_DOWN = "GLUE_DOWN"
    LOOSE_LAY = "LOOSE_LAY"
    CLICK_LOCK_SPC = "CLICK_LOCK_SPC"
    CLICK_LOCK_WPC = "CLICK_LOCK_WPC"


class AttachedUnderlaymentType(str, Enum):
    NONE = "NONE"
    IXPE_1MM = "IXPE_1MM"
    EVA_1_5MM = "EVA_1_5MM"
    CORK_2MM = "CORK_2MM"


class ProfileFamily(str, Enum):
    NONE = "NONE"
    UNILIN_5G = "UNILIN_5G"
    VALINGE_2G = "VALINGE_2G"
    DROP_LOCK = "DROP_LOCK"


class CertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    TESTING = "TESTING"
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    DECERTIFIED = "DECERTIFIED"


class CommercialStatus(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    RELEASED = "RELEASED"
    HOLD = "HOLD"
    DISCONTINUED = "DISCONTINUED"


class LineType(str, Enum):
    MULTI_DAY_PRESS = "MULTI_DAY_PRESS"
    CALENDER = "CALENDER"


class PressLineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    DOWN = "DOWN"


class TestPanelStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_TEST = "IN_TEST"
    PASSED = "PASSED"
    FAILED = "FAILED"
    RETEST_REQUIRED = "RETEST_REQUIRED"
    VOIDED = "VOIDED"


class TestType(str, Enum):
    RESIDUAL_INDENTATION = "RESIDUAL_INDENTATION"
    DIMENSIONAL_STABILITY_HEAT = "DIMENSIONAL_STABILITY_HEAT"
    SLIP_RESISTANCE = "SLIP_RESISTANCE"
    PEEL_ADHESION_DELAMINATION = "PEEL_ADHESION_DELAMINATION"
    LOCK_SHEAR = "LOCK_SHEAR"


class TestOutcome(str, Enum):
    PASS = "PASS"
    MARGINAL = "MARGINAL"
    FAIL = "FAIL"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    SETUP = "SETUP"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class QcDisposition(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    SCRAPPED = "SCRAPPED"


class BatchStatus(str, Enum):
    IN_PRODUCTION = "IN_PRODUCTION"
    IN_STOCK = "IN_STOCK"
    HELD = "HELD"
    SCRAPPED = "SCRAPPED"


class AllocationStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class SubstitutionPolicy(str, Enum):
    STRICT_SKU = "STRICT_SKU"
    ALLOW_UNDERLAYMENT_UPGRADE = "ALLOW_UNDERLAYMENT_UPGRADE"
    ALLOW_WEAR_LAYER_UPGRADE = "ALLOW_WEAR_LAYER_UPGRADE"


class SubstitutionKind(str, Enum):
    EXACT = "EXACT"
    UNDERLAYMENT_UPGRADE = "UNDERLAYMENT_UPGRADE"
    WEAR_LAYER_UPGRADE = "WEAR_LAYER_UPGRADE"


class AllocationLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class VoidReason(str, Enum):
    ALLOCATION_RELEASED = "ALLOCATION_RELEASED"
    ALLOCATION_CANCELLED = "ALLOCATION_CANCELLED"
    BATCH_HELD = "BATCH_HELD"
    BATCH_SCRAPPED = "BATCH_SCRAPPED"


class ClaimType(str, Enum):
    WEAR_LAYER_WEARTHROUGH = "WEAR_LAYER_WEARTHROUGH"
    DELAMINATION = "DELAMINATION"
    DIMENSIONAL_MOVEMENT = "DIMENSIONAL_MOVEMENT"
    LOCK_FAILURE = "LOCK_FAILURE"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGE = "TRIAGE"
    ADJUDICATION_READY = "ADJUDICATION_READY"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReviewOutcome(str, Enum):
    DEFECT_CONFIRMED = "DEFECT_CONFIRMED"
    NO_DEFECT = "NO_DEFECT"
    INCONCLUSIVE = "INCONCLUSIVE"


class ReviewKind(str, Enum):
    MATERIALS = "MATERIALS"
    FIELD = "FIELD"


class SettlementVariant(str, Enum):
    PRORATED_STRAIGHT_LINE = "PRORATED_STRAIGHT_LINE"
    STEPPED_SCHEDULE = "STEPPED_SCHEDULE"


# ---------------------------------------------------------------------------
# Response shapes.
#
# PRD 2.4: "Most resources additionally carry `updated_at` ... and `version`".
# `TestResult` is the single exception: "a TestResult row carries only `id` and
# `created_at`. It has neither `updated_at` nor `version`", so its TypedDict
# below deliberately omits both.
# ---------------------------------------------------------------------------


class Distributor(TypedDict):
    id: str
    account_code: str
    name: str
    territory_code: str
    certified_installer_program: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RawMaterial(TypedDict):
    id: str
    material_code: str
    name: str
    category: str
    cost_per_kg_cents: int
    indentation_index: float
    thermal_stability_index: float
    plasticizer_migration_index: float
    max_phr: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Formulation(TypedDict):
    id: str
    formulation_code: str
    supersedes_formulation_id: Optional[str]
    status: str
    revision: int
    cost_basis: str
    rejection_count: int
    open_revision_count: int
    authored_by_user_id: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    resin_phr: float
    plasticizer_phr: float
    filler_phr: float
    stabilizer_phr: float
    total_phr: float
    blended_cost_per_kg_cents: Optional[int]
    performance_score: Optional[float]
    indentation_resistance_class: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FormulationComponent(TypedDict):
    id: str
    formulation_id: str
    raw_material_id: str
    phr: float
    material_cost_snapshot_cents: Optional[int]
    snapshot_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DesignLicense(TypedDict):
    id: str
    license_code: str
    licensor_name: str
    license_type: str
    royalty_rate_bps: int
    valid_from: str
    valid_until: str
    term_volume_cap_sqm: float
    territory_codes: List[str]
    status: str
    reserved_volume_sqm: float
    consumed_volume_sqm: float
    accrued_royalty_cents: int
    supersedes_license_id: Optional[str]
    amendment_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrintFilm(TypedDict):
    id: str
    design_code: str
    license_id: str
    pattern_repeat_mm_length: float
    pattern_repeat_mm_width: float
    registration_tolerance_mm: float
    emboss_plate_code: str
    emboss_alignment_offset_mm: float
    master_roll_sets: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductSku(TypedDict):
    id: str
    sku_code: str
    formulation_id: str
    print_film_id: str
    construction_type: str
    wear_layer_mil: float
    overall_thickness_mm: float
    royalty_basis_price_cents_per_sqm: int
    waterproof_rated: bool
    attached_underlayment_type: str
    profile_family: str
    tongue_thickness_target_mm: Optional[float]
    tolerance_plus_mm: Optional[float]
    tolerance_minus_mm: Optional[float]
    target_lock_shear_n_per_mm: Optional[float]
    target_margin_bps: int
    warranty_years: int
    light_commercial_warranty_years: int
    certification_status: str
    commercial_status: str
    pinned_formulation_version: Optional[int]
    pinned_print_film_version: Optional[int]
    pin_stale: bool
    standard_cost_cents_per_sqm: Optional[int]
    list_price_cents_per_sqm: Optional[int]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PressLine(TypedDict):
    id: str
    line_code: str
    line_type: str
    min_thickness_mm: float
    max_thickness_mm: float
    changeover_minutes: int
    curl_control_index: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TestPanel(TypedDict):
    id: str
    panel_code: str
    sku_id: str
    status: str
    required_test_types: List[str]
    attempt_no: int
    retest_count: int
    started_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestResult(TypedDict):
    """PRD 2.4: a TestResult row carries only `id` and `created_at`."""

    id: str
    test_panel_id: str
    test_type: str
    measured_value: float
    unit: str
    spec_limit: float
    outcome: str
    attempt_no: int
    recorded_by_user_id: str
    created_at: str


class ProductionRun(TypedDict):
    id: str
    run_code: str
    sku_id: str
    press_line_id: str
    planned_start_utc: str
    planned_end_utc: str
    planned_quantity_sqm: float
    actual_quantity_sqm: float
    run_status: str
    qc_disposition: str
    changeover_minutes_applied: Optional[int]
    royalty_accrued_cents: int
    pattern_waste_sqm: Optional[float]
    registration_within_tolerance: Optional[bool]
    curl_within_tolerance: Optional[bool]
    emboss_within_tolerance: Optional[bool]
    tongue_within_tolerance: Optional[bool]
    auto_disposition_recommendation: Optional[str]
    abort_reason: Optional[str]
    completed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict):
    id: str
    batch_code: str
    production_run_id: str
    sku_id: str
    quantity_sqm: float
    available_quantity_sqm: float
    wear_layer_measured_mil: float
    status: str
    hold_reason: Optional[str]
    held_by_user_id: Optional[str]
    traceability_snapshot: dict
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    allocation_code: str
    distributor_id: str
    sku_id: str
    requested_quantity_sqm: float
    allocated_quantity_sqm: float
    substitution_policy: str
    upgrade_cost_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict):
    id: str
    allocation_id: str
    batch_id: str
    quantity_sqm: float
    substitution_kind: str
    upgrade_cost_delta_cents: int
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    claim_code: str
    batch_id: str
    distributor_id: str
    claim_type: str
    claimed_area_sqm: float
    installed_on: str
    reported_on: str
    installed_by_certified_installer: bool
    status: str
    required_reviews: Optional[List[str]]
    materials_review_outcome: Optional[str]
    field_review_outcome: Optional[str]
    assigned_adjuster_user_id: Optional[str]
    elapsed_months: Optional[int]
    settlement_variant: Optional[str]
    replacement_value_cents: Optional[int]
    labor_allowance_cents: Optional[int]
    settlement_amount_cents: Optional[int]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
