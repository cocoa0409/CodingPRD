"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource type carries the four
system-managed fields id + created_at + updated_at + version (PRD section on
common resource properties: "No resource type in this system omits
`updated_at` or `version`").
"""
from enum import Enum
from typing import List, Optional, TypedDict


class MarketCode(str, Enum):
    US_FDA = "US_FDA"
    CA_CFIA = "CA_CFIA"


class ProductCategory(str, Enum):
    BAKED_GOOD = "BAKED_GOOD"
    BEVERAGE = "BEVERAGE"
    CEREAL = "CEREAL"
    SNACK = "SNACK"
    DAIRY = "DAIRY"
    SAUCE = "SAUCE"
    CONFECTION = "CONFECTION"
    FROZEN_DESSERT = "FROZEN_DESSERT"


class AllergenTag(str, Enum):
    MILK = "MILK"
    EGGS = "EGGS"
    FISH = "FISH"
    SHELLFISH = "SHELLFISH"
    TREE_NUTS = "TREE_NUTS"
    PEANUTS = "PEANUTS"
    WHEAT = "WHEAT"
    SOYBEAN = "SOYBEAN"
    SESAME = "SESAME"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class LabAnalysisStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PanelMethod(str, Enum):
    DATABASE = "DATABASE"
    LAB = "LAB"


class PanelStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"


class LabelMode(str, Enum):
    SINGLE_SERVING = "SINGLE_SERVING"
    DUAL_COLUMN = "DUAL_COLUMN"
    STANDARD = "STANDARD"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    WITHDRAWN = "WITHDRAWN"


class ReleaseStatus(str, Enum):
    NOT_RELEASED = "NOT_RELEASED"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class ContentStatus(str, Enum):
    READY = "READY"
    NEEDS_REVISION = "NEEDS_REVISION"


class ClaimType(str, Enum):
    LOW_FAT = "LOW_FAT"
    FAT_FREE = "FAT_FREE"
    LOW_SODIUM = "LOW_SODIUM"
    HIGH_FIBER = "HIGH_FIBER"
    SUGAR_FREE = "SUGAR_FREE"
    LOW_CALORIE = "LOW_CALORIE"


class ClaimStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    NOT_REQUIRED = "NOT_REQUIRED"
    SUSPENDED = "SUSPENDED"


class Disqualifier(str, Enum):
    NONE = "NONE"
    FAT = "FAT"
    SATFAT = "SATFAT"
    CHOL = "CHOL"
    SODIUM = "SODIUM"


class VariantStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DeclaredFormat(str, Enum):
    STANDARD_VERTICAL = "STANDARD_VERTICAL"
    SIMPLIFIED = "SIMPLIFIED"
    TABULAR = "TABULAR"
    LINEAR = "LINEAR"


class FormatCheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FormatViolation(str, Enum):
    FORMAT_NOT_ALLOWED_FOR_PACKAGE = "FORMAT_NOT_ALLOWED_FOR_PACKAGE"
    TYPE_SIZE_BELOW_MIN = "TYPE_SIZE_BELOW_MIN"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FINDINGS_LOGGED = "FINDINGS_LOGGED"
    CLOSED = "CLOSED"


class AuditResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ScoringMethod(str, Enum):
    BINARY = "BINARY"
    WEIGHTED = "WEIGHTED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class FieldRef(str, Enum):
    INGREDIENT_LIST = "INGREDIENT_LIST"
    CONTAINS_STATEMENT = "CONTAINS_STATEMENT"
    NUTRITION_VALUES = "NUTRITION_VALUES"
    SERVING_SIZE = "SERVING_SIZE"
    CLAIM_TEXT = "CLAIM_TEXT"
    FORMAT = "FORMAT"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLIENT_REP = "ClientRep"
    LABEL_ANALYST = "LabelAnalyst"
    REGULATORY_REVIEWER = "RegulatoryReviewer"
    QUALITY_MANAGER = "QualityManager"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


class Client(TypedDict, total=False):
    id: str
    name: str
    home_market_code: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    client_id: str
    name: str
    product_category: str
    net_weight_g: float
    household_unit_name: Optional[str]
    household_unit_weight_g: Optional[float]
    total_surface_area_sq_in: float
    pdp_area_sq_in: float
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict, total=False):
    id: str
    client_id: str
    name: str
    allergen_tags: List[str]
    kcal_per_100g: Optional[float]
    fat_g_per_100g: Optional[float]
    satfat_g_per_100g: Optional[float]
    chol_mg_per_100g: Optional[float]
    sodium_mg_per_100g: Optional[float]
    carb_g_per_100g: Optional[float]
    fiber_g_per_100g: Optional[float]
    sugar_g_per_100g: Optional[float]
    protein_g_per_100g: Optional[float]
    created_at: str
    updated_at: str
    version: int


class RecipeLine(TypedDict):
    ingredient_id: str
    quantity_g: float


class Recipe(TypedDict, total=False):
    id: str
    product_id: str
    name: str
    yield_factor: float
    lines: List[RecipeLine]
    status: str
    latest_validated_lab_analysis_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabAnalysis(TypedDict, total=False):
    id: str
    recipe_id: str
    lab_report_ref: str
    kcal_per_100g: float
    fat_g_per_100g: float
    satfat_g_per_100g: float
    chol_mg_per_100g: float
    sodium_mg_per_100g: float
    carb_g_per_100g: float
    fiber_g_per_100g: float
    sugar_g_per_100g: float
    protein_g_per_100g: float
    status: str
    reviewed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NutrientPanel(TypedDict, total=False):
    id: str
    recipe_id: str
    method: str
    status: str
    basis_lab_analysis_id: Optional[str]
    kcal_per_100g: float
    fat_g_per_100g: float
    satfat_g_per_100g: float
    chol_mg_per_100g: float
    sodium_mg_per_100g: float
    carb_g_per_100g: float
    fiber_g_per_100g: float
    sugar_g_per_100g: float
    protein_g_per_100g: float
    created_at: str
    updated_at: str
    version: int


class RaccAssignment(TypedDict, total=False):
    id: str
    product_id: str
    market_code: str
    racc_g: float
    label_mode: str
    serving_size_g: float
    serving_household_units: float
    servings_per_container: float
    created_at: str
    updated_at: str
    version: int


class LabelVersion(TypedDict, total=False):
    id: str
    product_id: str
    market_code: str
    nutrient_basis: str
    racc_assignment_id: str
    declared_format: str
    declared_type_size_in: float
    ingredient_statement_text: str
    contains_text: str
    review_status: str
    release_status: str
    content_status: str
    panel_snapshot_id: Optional[str]
    review_round: int
    prepared_by: str
    approved_by: Optional[str]
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimAssessment(TypedDict, total=False):
    id: str
    label_version_id: str
    claim_type: str
    status: str
    evaluated_value_per_racc: Optional[float]
    threshold_value: Optional[float]
    disqualified_by: Optional[str]
    basis_panel_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketVariant(TypedDict, total=False):
    id: str
    label_version_id: str
    market_code: str
    effective_start: str
    effective_end: Optional[str]
    translated_contains_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FormatCheck(TypedDict, total=False):
    id: str
    label_version_id: str
    result: str
    violations: List[str]
    allowed_formats: List[str]
    min_type_size_in: float
    created_at: str
    updated_at: str
    version: int


class ArtworkAudit(TypedDict, total=False):
    id: str
    client_id: str
    product_id: str
    label_version_id: str
    facility_code: str
    scheduled_start: str
    scheduled_end: str
    scoring_method: str
    status: str
    conformance_score: Optional[float]
    result: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    audit_id: str
    severity: str
    field_ref: str
    on_pack_text: str
    approved_text: str
    created_at: str
    updated_at: str
    version: int
