"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.11, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    BRAND_REP = "BrandRep"
    PRODUCTION_PLANNER = "ProductionPlanner"
    PRODUCTION_OPERATOR = "ProductionOperator"
    QA_CHEMIST = "QAChemist"
    QA_MANAGER = "QAManager"


class DosageForm(str, Enum):
    TABLET = "TABLET"
    CAPSULE = "CAPSULE"
    POWDER = "POWDER"
    SOFTGEL = "SOFTGEL"
    LIQUID = "LIQUID"


class AllergenClass(str, Enum):
    NONE = "NONE"
    GLUTEN = "GLUTEN"
    MILK = "MILK"
    SOY = "SOY"
    EGG = "EGG"
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    FISH = "FISH"
    SHELLFISH = "SHELLFISH"
    SESAME = "SESAME"


class OverageBasis(str, Enum):
    THEORETICAL = "THEORETICAL"
    LABEL_CLAIM = "LABEL_CLAIM"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class MaterialLotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    IDENTITY_PASSED = "IDENTITY_PASSED"
    IDENTITY_FAILED = "IDENTITY_FAILED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"


class IdentityTestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COA_APPROVED = "COA_APPROVED"
    COA_REJECTED = "COA_REJECTED"


class IdentityTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CoaReviewOutcome(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ManufacturingOrderStatus(str, Enum):
    PLACED = "PLACED"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BatchProductionStatus(str, Enum):
    CREATED = "CREATED"
    IN_PROCESS = "IN_PROCESS"
    COMPLETED = "COMPLETED"
    RECORD_REVIEWED = "RECORD_REVIEWED"
    CANCELLED = "CANCELLED"


class BatchQualityStatus(str, Enum):
    PENDING_QC = "PENDING_QC"
    ASSAY_HOLD = "ASSAY_HOLD"
    QC_READY = "QC_READY"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"


class BatchConsumptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class LineCleaningStatus(str, Enum):
    CLEAN_VALIDATED = "CLEAN_VALIDATED"
    DIRTY = "DIRTY"
    CLEAN_PENDING_VALIDATION = "CLEAN_PENDING_VALIDATION"


class CleaningValidationStatus(str, Enum):
    RECORDED = "RECORDED"
    SWAB_PASSED = "SWAB_PASSED"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"


class SwabResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AssayResultStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AssayReviewOutcome(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class StabilityProtocol(str, Enum):
    REAL_TIME = "REAL_TIME"
    ACCELERATED = "ACCELERATED"


class StabilityStudyStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"


class RecallScopeType(str, Enum):
    MATERIAL_LOT = "MATERIAL_LOT"
    BATCH = "BATCH"


class RecallEventStatus(str, Enum):
    INITIATED = "INITIATED"
    TRACED = "TRACED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Every resource carries the common system-managed fields
# id / created_at / updated_at / version (PRD §2.4).
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    brand_name: str
    committed_order_value_cents: int
    open_order_count: int
    lifetime_receipts_cents: int
    open_recall_count: int
    created_at: str
    updated_at: str
    version: int


class PriceTier(TypedDict):
    min_qty: int
    unit_price_cents: int


class Formula(TypedDict, total=False):
    id: str
    customer_id: str
    name: str
    dosage_form: str
    allergen_class: str
    min_order_qty: int
    batch_size_units: int
    shelf_life_months: int
    overage_basis: str
    price_tiers: List[PriceTier]
    revised_from_formula_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FormulaLine(TypedDict, total=False):
    id: str
    formula_id: str
    raw_material_id: str
    theoretical_qty_mg_per_unit: float
    overage_pct: float
    is_label_claim_line: bool
    label_claim_mg_per_unit: Optional[float]
    planned_weigh_qty_mg: Optional[float]
    created_at: str
    updated_at: str
    version: int


class RawMaterial(TypedDict, total=False):
    id: str
    name: str
    allergen_class: str
    created_at: str
    updated_at: str
    version: int


class MaterialLot(TypedDict, total=False):
    id: str
    raw_material_id: str
    supplier_name: str
    supplier_coa_ref: str
    qty_received: float
    qty_remaining: float
    status: str
    created_at: str
    updated_at: str
    version: int


class IdentityTest(TypedDict, total=False):
    id: str
    material_lot_id: str
    result: str
    coa_match: bool
    tested_by_id: str
    review_outcome: Optional[str]
    reviewed_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ManufacturingOrder(TypedDict, total=False):
    id: str
    customer_id: str
    formula_id: str
    formula_version_at_order: int
    ordered_qty: int
    unit_price_cents: int
    total_price_cents: int
    recall_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict, total=False):
    id: str
    mo_id: str
    production_line_id: str
    theoretical_units: int
    planned_start: str
    planned_end: str
    actual_yield_units: Optional[int]
    actual_bulk_mass_g: Optional[float]
    yield_variance_pct: Optional[float]
    completed_at: Optional[str]
    recorded_by_id: Optional[str]
    reviewed_by_id: Optional[str]
    expiry_date: Optional[str]
    production_status: str
    quality_status: str
    created_at: str
    updated_at: str
    version: int


class BatchConsumption(TypedDict, total=False):
    id: str
    batch_id: str
    material_lot_id: str
    qty_consumed: float
    status: str
    voided_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict, total=False):
    id: str
    name: str
    cleaning_status: str
    current_allergen_class: str
    created_at: str
    updated_at: str
    version: int


class CleaningValidation(TypedDict, total=False):
    id: str
    production_line_id: str
    notes: Optional[str]
    recorded_by_id: str
    swab_result: Optional[str]
    swabbed_by_id: Optional[str]
    approved_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AssayResult(TypedDict, total=False):
    id: str
    batch_id: str
    assayed_mg_per_unit: float
    label_claim_mg_per_unit: float
    pct_of_claim: float
    submitted_by_id: str
    review_outcome: Optional[str]
    reviewed_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PullResult(TypedDict):
    pull_month: int
    passed: bool


class StabilityStudy(TypedDict, total=False):
    id: str
    batch_id: str
    chamber_id: str
    protocol: str
    pull_results: Optional[List[PullResult]]
    supported_months: Optional[int]
    assigned_expiry_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StabilityChamber(TypedDict, total=False):
    id: str
    name: str
    capacity_units: int
    occupied_units: int
    created_at: str
    updated_at: str
    version: int


class RecallEvent(TypedDict, total=False):
    id: str
    scope_type: str
    scope_id: str
    reason: str
    affected_batch_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
