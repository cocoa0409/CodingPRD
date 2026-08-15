"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Allergen(str, Enum):
    MILK = "MILK"
    SOY = "SOY"
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    WHEAT = "WHEAT"
    EGG = "EGG"
    SESAME = "SESAME"


class SupplierQualificationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class IngredientCategory(str, Enum):
    PROTEIN = "PROTEIN"
    SWEETENER = "SWEETENER"
    BINDER = "BINDER"
    FAT = "FAT"
    FLAVOR = "FLAVOR"
    ADDITIVE = "ADDITIVE"


class IngredientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class LotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PricingMode(str, Enum):
    MARGINAL = "MARGINAL"
    AVERAGE = "AVERAGE"


class AgreementStatus(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FormulaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class RevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    NUTRITION_VERIFIED = "NUTRITION_VERIFIED"
    CLAIM_REVIEW = "CLAIM_REVIEW"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ClaimTag(str, Enum):
    HIGH_PROTEIN = "HIGH_PROTEIN"
    GOOD_SOURCE_PROTEIN = "GOOD_SOURCE_PROTEIN"
    LOW_SUGAR = "LOW_SUGAR"
    GLUTEN_FREE = "GLUTEN_FREE"


class ClaimType(str, Enum):
    NUTRIENT_CONTENT = "NUTRIENT_CONTENT"
    STRUCTURE_FUNCTION = "STRUCTURE_FUNCTION"


class LineType(str, Enum):
    SLAB_FORM_CUT = "SLAB_FORM_CUT"


class SlotStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    PRE_RUN_VERIFIED = "PRE_RUN_VERIFIED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReleaseStatus(str, Enum):
    NOT_READY = "NOT_READY"
    PENDING_QC = "PENDING_QC"
    RELEASED = "RELEASED"
    HOLD_REWORK = "HOLD_REWORK"
    SCRAPPED = "SCRAPPED"


class CancelReason(str, Enum):
    OPERATOR_CANCEL = "OPERATOR_CANCEL"
    FORMULA_SUPERSEDED = "FORMULA_SUPERSEDED"
    INGREDIENT_SHORTAGE = "INGREDIENT_SHORTAGE"


class ChangeoverLevel(str, Enum):
    NONE = "NONE"
    DRY_CLEAN = "DRY_CLEAN"
    WET_CLEAN = "WET_CLEAN"
    SWAB_VALIDATE = "SWAB_VALIDATE"


class ChangeoverStatus(str, Enum):
    PENDING = "PENDING"
    CLEANING_LOGGED = "CLEANING_LOGGED"
    SWAB_RECORDED = "SWAB_RECORDED"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StudyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TERMINATED = "TERMINATED"


class PullStatus(str, Enum):
    RECORDED = "RECORDED"
    MISSED = "MISSED"


class QcDisposition(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ReleaseDecision(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    HOLD_REWORK = "HOLD_REWORK"
    SCRAPPED = "SCRAPPED"


class ClaimReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    FORMULATION_SCIENTIST = "FormulationScientist"
    QUALITY_MANAGER = "QualityManager"
    PRODUCTION_PLANNER = "ProductionPlanner"
    LAB_TECHNICIAN = "LabTechnician"
    BRAND_CUSTOMER_REP = "BrandCustomerRep"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries id / created_at / updated_at /
# version (PRD §2.4).
# ---------------------------------------------------------------------------

class Supplier(TypedDict, total=False):
    id: str
    name: str
    qualification_status: str
    allergens_handled: List[str]
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict, total=False):
    id: str
    name: str
    category: str
    allergen_tags: List[str]
    nominal_protein_pct: Optional[float]
    nominal_sweetness_factor: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class IngredientLot(TypedDict, total=False):
    id: str
    ingredient_id: str
    supplier_id: str
    lot_code: str
    received_qty_kg: float
    coa_protein_pct: Optional[float]
    coa_sweetness_factor: Optional[float]
    received_at: str
    available_qty_kg: float
    reserved_qty_kg: float
    consumed_qty_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BrandCustomer(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TierBreak(TypedDict):
    upto_cases: int
    rate_cents_per_case: int


class ManufacturingAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    pricing_mode: str
    moq_cases_per_run: int
    committed_cases_per_quarter: int
    tier_breaks: List[TierBreak]
    quarter_start: str
    produced_cases_current_quarter: int
    shortfall_cases: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Formula(TypedDict, total=False):
    id: str
    customer_id: str
    name: str
    bar_weight_g: float
    serving_count_per_bar: int
    status: str
    approved_revision_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IngredientLine(TypedDict):
    ingredient_id: str
    qty_kg_per_batch: float
    is_protein_contributor: bool


class FormulaRevision(TypedDict, total=False):
    id: str
    formula_id: str
    revision_no: int
    ingredient_lines: List[IngredientLine]
    batch_size_kg: float
    target_protein_g_per_serving: float
    claim_tags: List[str]
    allergen_profile: List[str]
    label_protein_g_per_serving: Optional[float]
    composite_protein_g_per_serving: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict, total=False):
    id: str
    name: str
    line_type: str
    capacity_kg_per_hour: float
    slab_weight_kg: float
    current_allergen_profile: List[str]
    last_wet_clean_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LineSlot(TypedDict, total=False):
    id: str
    line_id: str
    run_id: str
    start_utc: str
    end_utc: str
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LotAllocation(TypedDict):
    lot_id: str
    ingredient_id: str
    qty_kg: float


class ProductionRun(TypedDict, total=False):
    id: str
    revision_id: str
    agreement_id: str
    line_id: str
    planned_cases: int
    batch_code: str
    reserved_lot_allocations: List[LotAllocation]
    ingredient_readiness: str
    provisional_sweetener_required_kg: float
    final_sweetener_required_kg: Optional[float]
    produced_cases: Optional[int]
    scrapped_cases: Optional[int]
    completed_utc: Optional[str]
    cancel_reason: Optional[str]
    status: str
    release_status: str
    created_at: str
    updated_at: str
    version: int


class ChangeoverEvent(TypedDict, total=False):
    id: str
    line_id: str
    from_run_id: Optional[str]
    to_run_id: str
    required_level: str
    swab_allergen_ppm: Optional[float]
    swab_recorded_by: Optional[str]
    validated_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShelfLifeStudy(TypedDict, total=False):
    id: str
    revision_id: str
    chamber_id: str
    shelf_position: str
    start_utc: str
    expiry_utc: str
    hardness_limit_n: float
    pull_interval_days: int
    projected_hardness_at_expiry_n: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShelfLifePull(TypedDict, total=False):
    id: str
    study_id: str
    pull_index: int
    due_utc: str
    recorded_utc: str
    hardness_n: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LotRelease(TypedDict, total=False):
    id: str
    run_id: str
    expected_cases: int
    yield_variance_pct: float
    qc_disposition: str
    qc_recorded_by: Optional[str]
    decision: str
    decided_by: Optional[str]
    retain_cases_stored: int
    created_at: str
    updated_at: str
    version: int


class RetainSample(TypedDict, total=False):
    id: str
    run_id: str
    bin_id: str
    cases_count: int
    retain_until_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimReview(TypedDict, total=False):
    id: str
    revision_id: str
    claim_tag: str
    claim_type: str
    structure_function_disclaimer: bool
    substantiation_ok: bool
    reviewer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
