"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FORMULATION_SCIENTIST = "FormulationScientist"
    QA_APPROVER = "QAApprover"
    QUALITY_ANALYST = "QualityAnalyst"
    TRIAL_COORDINATOR = "TrialCoordinator"
    PRODUCTION_PLANNER = "ProductionPlanner"
    LINE_OPERATOR = "LineOperator"
    REGULATORY_AFFAIRS = "RegulatoryAffairs"
    STATE_REGULATOR = "StateRegulator"


class BrandOwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SupplierApprovalState(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class IngredientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AllergenClass(str, Enum):
    NONE = "NONE"
    POULTRY = "POULTRY"
    BEEF = "BEEF"
    FISH = "FISH"
    DAIRY = "DAIRY"
    GRAIN = "GRAIN"
    OTHER = "OTHER"


class PairingApprovalState(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    NUTRIENT_REVIEW = "NUTRIENT_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"


class LifeStage(str, Enum):
    GROWTH = "GROWTH"
    ADULT_MAINTENANCE = "ADULT_MAINTENANCE"
    ALL_LIFE_STAGES = "ALL_LIFE_STAGES"
    GESTATION_LACTATION = "GESTATION_LACTATION"


class AdequacyBasis(str, Enum):
    FORMULATION = "FORMULATION"
    FEEDING_TRIAL = "FEEDING_TRIAL"


class ProfileBasis(str, Enum):
    FORMULATION_CALC = "FORMULATION_CALC"
    LAB_ANALYSIS = "LAB_ANALYSIS"


class AafcoCompliance(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"


class TrialStatus(str, Enum):
    PLANNED = "PLANNED"
    ENROLLING = "ENROLLING"
    RUNNING = "RUNNING"
    ANALYSIS = "ANALYSIS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class BatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED_FOR_PRODUCTION = "RELEASED_FOR_PRODUCTION"
    IN_PROCESS = "IN_PROCESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    RELEASED = "RELEASED"
    RECALLED = "RECALLED"


class SampleType(str, Enum):
    FIRST = "FIRST"
    MIDDLE = "MIDDLE"
    LAST = "LAST"
    COMPOSITE = "COMPOSITE"


class SampleVerdict(str, Enum):
    PENDING = "PENDING"
    WITHIN_LABEL = "WITHIN_LABEL"
    LABEL_VIOLATION = "LABEL_VIOLATION"


class LabelCompliance(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    MISBRANDED = "MISBRANDED"


class RegistrationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ComplaintStatus(str, Enum):
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    ESCALATED_RECALL = "ESCALATED_RECALL"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


class Severity(str, Enum):
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    LIFE_THREATENING = "LIFE_THREATENING"
    DEATH = "DEATH"


class ComplaintCategory(str, Enum):
    PALATABILITY = "PALATABILITY"
    FOREIGN_MATERIAL = "FOREIGN_MATERIAL"
    ILLNESS = "ILLNESS"
    LABEL_DEFECT = "LABEL_DEFECT"
    PACKAGING = "PACKAGING"


class RecallClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class RecallStatus(str, Enum):
    INITIATED = "INITIATED"
    EFFECTIVENESS_CHECK = "EFFECTIVENESS_CHECK"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


# All fifteen resources carry the common system-managed properties of PRD §2.4
# (id, created_at, updated_at, version).


class BrandOwner(TypedDict, total=False):
    id: str
    legal_name: str
    fein: str
    contact_email: str
    status: str
    open_recall_count: int
    complaint_score: float
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    supplier_name: str
    fsma_facility_id: str
    country_code: str
    approval_state: str
    risk_tier: str
    approved_ingredient_count: int
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict, total=False):
    id: str
    aafco_name: str
    ingredient_code: str
    nutrient_matrix: Dict[str, float]
    allergen_class: str
    requires_coa: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplierIngredientApproval(TypedDict, total=False):
    id: str
    supplier_id: str
    ingredient_id: str
    approval_state: str
    coa_document_ref: str
    review_notes: str
    decided_by: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Formula(TypedDict, total=False):
    id: str
    brand_owner_id: str
    formula_code: str
    product_name: str
    species: str
    life_stage: str
    adequacy_basis: str
    status: str
    revision_number: int
    parent_formula_id: Optional[str]
    substantiation_locked_version: Optional[int]
    total_batch_count: int
    open_recall_flag: bool
    created_at: str
    updated_at: str
    version: int


class FormulaIngredient(TypedDict, total=False):
    id: str
    formula_id: str
    ingredient_id: str
    inclusion_pct: float
    processing_note: str
    created_at: str
    updated_at: str
    version: int


class NutrientProfile(TypedDict, total=False):
    id: str
    formula_id: str
    profile_basis: str
    crude_protein_min_pct: float
    crude_fat_min_pct: float
    crude_fiber_max_pct: float
    moisture_max_pct: float
    calcium_min_pct: float
    phosphorus_min_pct: float
    metabolizable_energy_kcal_per_kg: float
    aafco_compliance: str
    created_at: str
    updated_at: str
    version: int


class FeedingTrialProtocol(TypedDict, total=False):
    id: str
    formula_id: str
    protocol_code: str
    animal_count: int
    duration_days: int
    status: str
    enrolled_count: int
    completed_count: int
    completion_ratio: float
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict, total=False):
    id: str
    formula_id: str
    planned_kg: float
    actual_kg: float
    line_id: str
    scheduled_start: str
    status: str
    yield_variance_pct: float
    created_at: str
    updated_at: str
    version: int


class BatchLotCode(TypedDict, total=False):
    id: str
    batch_id: str
    lot_code: str
    packaged_units: int
    best_by_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LabSample(TypedDict, total=False):
    id: str
    batch_id: str
    sample_type: str
    measured_protein_pct: float
    measured_fat_pct: float
    measured_fiber_pct: float
    measured_moisture_pct: float
    verdict: str
    created_at: str
    updated_at: str
    version: int


class GuaranteedAnalysisReport(TypedDict, total=False):
    id: str
    batch_id: str
    composite_protein_pct: float
    composite_fat_pct: float
    composite_fiber_pct: float
    composite_moisture_pct: float
    label_compliance: str
    deviation_index: float
    created_at: str
    updated_at: str
    version: int


class StateRegistration(TypedDict, total=False):
    id: str
    formula_id: str
    state_code: str
    label_revision_ref: int
    status: str
    fee_cents: int
    submitted_at: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplaintCase(TypedDict, total=False):
    id: str
    brand_owner_id: str
    formula_id: str
    batch_id: Optional[str]
    severity: str
    category: str
    status: str
    triage_score: float
    adverse_event_flag: bool
    created_at: str
    updated_at: str
    version: int


class RecallAction(TypedDict, total=False):
    id: str
    formula_id: str
    scope_batch_ids: List[str]
    recall_class: str
    reason: str
    status: str
    affected_lot_count: int
    effectiveness_pct: float
    created_at: str
    updated_at: str
    version: int
