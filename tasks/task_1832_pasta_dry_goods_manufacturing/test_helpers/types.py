"""Domain types: entity TypedDicts, status enums, role enum for the PRD."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    PROCUREMENT_MANAGER = "ProcurementManager"
    QA_TECHNICIAN = "QATechnician"
    QA_MANAGER = "QAManager"
    PRODUCTION_OPERATOR = "ProductionOperator"
    WAREHOUSE_CLERK = "WarehouseClerk"


class IngredientType(str, Enum):
    SEMOLINA = "SEMOLINA"
    DURUM_SEMOLINA = "DURUM_SEMOLINA"
    RICE_FLOUR = "RICE_FLOUR"


class PricingMethod(str, Enum):
    INDEX_LAGGED = "INDEX_LAGGED"
    SPOT_BLEND = "SPOT_BLEND"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class Grade(str, Enum):
    GRADE_A = "GRADE_A"
    GRADE_B = "GRADE_B"
    GRADE_REJECT = "GRADE_REJECT"


class LotStatus(str, Enum):
    QUARANTINED = "QUARANTINED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class BrandType(str, Enum):
    BRANDED = "BRANDED"
    PRIVATE_LABEL = "PRIVATE_LABEL"


class ShapeFamily(str, Enum):
    LONG_CUT = "LONG_CUT"
    SHORT_CUT = "SHORT_CUT"
    SPECIALTY = "SPECIALTY"


class DryingCurve(str, Enum):
    STANDARD = "STANDARD"
    HIGH_TEMP = "HIGH_TEMP"
    LOW_TEMP = "LOW_TEMP"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class GlutenPosture(str, Enum):
    GLUTEN_EXPOSED = "GLUTEN_EXPOSED"
    CLEANING_IN_PROGRESS = "CLEANING_IN_PROGRESS"
    AWAITING_SWAB = "AWAITING_SWAB"
    GF_VALIDATED = "GF_VALIDATED"


class DieStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MOUNTED = "MOUNTED"
    IN_CLEANING = "IN_CLEANING"
    RETIRED = "RETIRED"


class ProductionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MIXING = "MIXING"
    EXTRUDING = "EXTRUDING"
    DRYING = "DRYING"
    PACKAGING = "PACKAGING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class QualityDisposition(str, Enum):
    PENDING_QA = "PENDING_QA"
    RELEASED = "RELEASED"
    HELD = "HELD"
    REJECTED = "REJECTED"


class DryingSessionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_LAB = "AWAITING_LAB"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class PackagingJobStatus(str, Enum):
    CREATED = "CREATED"
    LABEL_VERIFIED = "LABEL_VERIFIED"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class GoodsLotStatus(str, Enum):
    CREATED = "CREATED"
    STORED = "STORED"
    RELEASED = "RELEASED"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class ZoneType(str, Enum):
    GLUTEN_FREE = "GLUTEN_FREE"
    CONVENTIONAL = "CONVENTIONAL"


class PestPosture(str, Enum):
    CLEAR = "CLEAR"
    MONITORING = "MONITORING"
    QUARANTINED = "QUARANTINED"


class Severity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    CRITICAL = "CRITICAL"


class RecordStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"


class TestType(str, Enum):
    LINE_SWAB = "LINE_SWAB"
    PRODUCT_TEST = "PRODUCT_TEST"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# --- Entity TypedDicts -------------------------------------------------------
# Entities with common fields carry id + created_at + updated_at + version.
# Append-only kinds (PriceIndexReading, RecipeIngredient) carry only id +
# created_at: no updated_at, no version.


class IngredientContract(TypedDict, total=False):
    id: str
    contract_code: str
    supplier_name: str
    ingredient_type: str
    base_price_cents_per_kg: int
    reference_index_value: float
    pricing_method: str
    effective_start: str
    effective_end: str
    cumulative_delivered_kg: float
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class PriceIndexReading(TypedDict, total=False):
    id: str
    created_at: str
    contract_id: str
    effective_date: str
    index_value: float


class SemolinaLot(TypedDict, total=False):
    id: str
    contract_id: str
    delivery_date: str
    received_weight_kg: float
    remaining_weight_kg: float
    consumed_kg: float
    cert_protein_pct: float
    cert_moisture_pct: float
    cert_gluten_index: float
    cert_falling_number_s: float
    lab_protein_pct: Optional[float]
    lab_moisture_pct: Optional[float]
    lab_gluten_index: Optional[float]
    lab_falling_number_s: Optional[float]
    cert_grade_score: float
    cert_grade: str
    lab_grade_score: Optional[float]
    lab_grade: Optional[str]
    unit_price_cents: int
    total_price_cents: int
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict, total=False):
    id: str
    recipe_name: str
    brand_type: str
    customer_name: Optional[str]
    shape_family: str
    gluten_free: bool
    target_moisture_pct: float
    drying_curve: str
    shelf_life_days: int
    min_remaining_shelf_life_pct: Optional[float]
    unit_weight_g: float
    units_per_case: int
    case_weight_limit_kg: float
    cases_per_pallet: int
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecipeIngredient(TypedDict, total=False):
    id: str
    created_at: str
    recipe_id: str
    ingredient_type: str
    percentage: float
    min_protein_pct: Optional[float]


class ProductionLine(TypedDict, total=False):
    id: str
    line_name: str
    gluten_posture: str
    cleaning_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExtrusionDie(TypedDict, total=False):
    id: str
    die_code: str
    shape_family: str
    rated_capacity_kg: float
    extruded_kg: float
    status: str
    mounted_line_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    recipe_id: str
    line_id: str
    semolina_lot_id: str
    pinned_recipe_version: int
    planned_input_kg: float
    scheduled_start: str
    scheduled_end: str
    changeover_minutes: int
    gluten_free: bool
    brand_type: str
    actual_yield_kg: Optional[float]
    actual_started_at: Optional[str]
    completed_at: Optional[str]
    production_status: str
    quality_disposition: str
    created_at: str
    updated_at: str
    version: int


class DryingSession(TypedDict, total=False):
    id: str
    run_id: str
    drying_curve: str
    initial_moisture_pct: float
    target_moisture_pct: float
    redry_count: int
    required_hours: int
    drying_started_at: str
    latest_inline_moisture_pct: Optional[float]
    latest_lab_moisture_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PackagingJob(TypedDict, total=False):
    id: str
    run_id: str
    status: str
    actual_yield_kg: float
    total_units: int
    units_per_case: int
    full_case_count: int
    partial_case_count: int
    scrapped_units: int
    case_count: int
    pallet_count: int
    labels_verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinishedGoodsLot(TypedDict, total=False):
    id: str
    packaging_job_id: str
    run_id: str
    zone_id: Optional[str]
    production_date: Optional[str]
    expiry_date: Optional[str]
    case_count: int
    pallet_count: int
    unit_count: int
    gluten_free: bool
    brand_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarehouseZone(TypedDict, total=False):
    id: str
    zone_name: str
    zone_type: str
    capacity_pallets: int
    pest_posture: str
    quarantined_at: Optional[str]
    occupied_pallets: int
    created_at: str
    updated_at: str
    version: int


class PestInspection(TypedDict, total=False):
    id: str
    zone_id: str
    severity: str
    notes: Optional[str]
    recorded_by_user_id: str
    status: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GlutenTest(TypedDict, total=False):
    id: str
    test_type: str
    line_id: Optional[str]
    run_id: Optional[str]
    result: str
    recorded_by_user_id: str
    status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
