"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the PRD resource model. The ten primary resources carry
id/created_at/updated_at/version; the three record-type resources
(GradeAssessment, ResidueTest, FlavoringApplication) are immutable and
carry only id/created_at (PRD §2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PROCUREMENT_LEAD = "ProcurementLead"
    SENSORY_GRADER = "SensoryGrader"
    QA_LAB_ANALYST = "QALabAnalyst"
    QA_MANAGER = "QAManager"
    BLEND_MASTER = "BlendMaster"
    PRODUCTION_PLANNER = "ProductionPlanner"
    ACCOUNT_MANAGER = "AccountManager"
    CERTIFICATION_OFFICER = "CertificationOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LeafLotStatus(str, Enum):
    REGISTERED = "REGISTERED"
    GRADED = "GRADED"
    LAB_SUBMITTED = "LAB_SUBMITTED"
    ON_HOLD = "ON_HOLD"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class LeafType(str, Enum):
    BLACK = "BLACK"
    GREEN = "GREEN"
    WHITE = "WHITE"
    OOLONG = "OOLONG"
    HERBAL = "HERBAL"


class CompositeGrade(str, Enum):
    NONE = "NONE"
    A = "A"
    B = "B"
    C = "C"
    REJECT = "REJECT"


class AssessmentGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    REJECT = "REJECT"


class ResidueVerdict(str, Enum):
    NONE = "NONE"
    PASS = "PASS"
    FAIL_SOFT = "FAIL_SOFT"
    FAIL_HARD = "FAIL_HARD"


class FlavoringStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AllergenTag(str, Enum):
    TREE_NUT = "TREE_NUT"
    SOY = "SOY"
    GLUTEN = "GLUTEN"
    LACTOSE = "LACTOSE"


class CertificationTarget(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    ORGANIC = "ORGANIC"
    FAIR_TRADE = "FAIR_TRADE"


class PackFormat(str, Enum):
    TEA_BAG = "TEA_BAG"
    LOOSE_PACK = "LOOSE_PACK"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    RECIPE_LOCKED = "RECIPE_LOCKED"
    ALLOCATED = "ALLOCATED"
    BLENDED = "BLENDED"
    FLAVORED = "FLAVORED"
    QC_REVIEW = "QC_REVIEW"
    ON_HOLD = "ON_HOLD"
    RELEASED = "RELEASED"
    RECALLED = "RECALLED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"


class LineType(str, Enum):
    TEA_BAG = "TEA_BAG"
    LOOSE_PACK = "LOOSE_PACK"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class CertType(str, Enum):
    ORGANIC = "ORGANIC"
    FAIR_TRADE = "FAIR_TRADE"


class CertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — primary resources (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Supplier(TypedDict):
    id: str
    name: str
    origin_region: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LeafLot(TypedDict):
    id: str
    supplier_id: str
    leaf_type: str
    harvest_date: str
    weight_kg: float
    cost_per_kg_cents: int
    moisture_pct: float
    remaining_weight_kg: float
    registered_by_user_id: str
    composite_grade: str
    latest_residue_verdict: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Flavoring(TypedDict):
    id: str
    name: str
    allergen_tags: List[str]
    natural_certified: bool
    cost_per_kg_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BlendRecipe(TypedDict):
    id: str
    name: str
    certification_target: str
    pack_format: str
    components: List[dict]
    flavoring_id: Optional[str]
    flavoring_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BlendBatch(TypedDict):
    id: str
    recipe_id: str
    recipe_version: int
    pack_format: str
    target_weight_kg: float
    required_components: List[dict]
    flavoring_kg: float
    allergen_tags: List[str]
    measured_moisture_pct: float
    yield_kg: float
    blended_by_user_id: str
    provisional_cost_cents: int
    final_cost_cents: int
    actual_weight_kg: float
    cert_charges: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class BatchLotAllocation(TypedDict):
    id: str
    batch_id: str
    lot_id: str
    allocated_kg: float
    line_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackagingLine(TypedDict):
    id: str
    name: str
    line_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    line_id: str
    batch_id: str
    contract_id: Optional[str]
    planned_start: str
    planned_end: str
    planned_units: int
    actual_units: int
    provisional_shelf_life_days: int
    final_shelf_life_days: int
    started_at: str
    completed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PrivateLabelContract(TypedDict):
    id: str
    customer_name: str
    recipe_id: str
    minimum_units_per_run: int
    contracted_total_units: int
    base_unit_price_cents: int
    contract_unit_price_cents: int
    fulfilled_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificateGrant(TypedDict):
    id: str
    supplier_id: str
    cert_type: str
    total_volume_kg: float
    consumed_volume_kg: float
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Record-type resources — immutable: only id + created_at (NO updated_at,
# NO version per PRD §2.4).
# ---------------------------------------------------------------------------

class GradeAssessment(TypedDict):
    id: str
    lot_id: str
    grader_user_id: str
    aroma_score: int
    briskness_score: int
    appearance_score: int
    composite_score: float
    composite_grade: str
    created_at: str


class ResidueTest(TypedDict):
    id: str
    lot_id: str
    lab_name: str
    measured_residue_ppm: float
    test_method: str
    submitted_by_user_id: str
    verdict: str
    test_round: int
    created_at: str


class FlavoringApplication(TypedDict):
    id: str
    batch_id: str
    flavoring_id: str
    applied_kg: float
    applied_by_user_id: str
    flavoring_cost_cents: int
    created_at: str
