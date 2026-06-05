"""Domain types: entity TypedDicts, status enums, role enum for the
Cannabis Seed-to-Sale Compliance API."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (the seven operational capacities declared by X-User-Role)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    STATE_REGULATOR = "StateRegulator"
    CULTIVATOR = "Cultivator"
    QA_LAB_USER = "QALabUser"
    COMPLIANCE_MANAGER = "ComplianceManager"
    DISTRIBUTION_AGENT = "DistributionAgent"
    BUDTENDER = "Budtender"
    INVENTORY_AUDITOR = "InventoryAuditor"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class LicenseType(str, Enum):
    CULTIVATION = "CULTIVATION"
    MANUFACTURING = "MANUFACTURING"
    RETAIL = "RETAIL"
    TESTING = "TESTING"
    DISTRIBUTION = "DISTRIBUTION"


class PlantBatchStatus(str, Enum):
    IMMATURE = "IMMATURE"
    VEGETATIVE = "VEGETATIVE"
    FLOWERING = "FLOWERING"
    HARVESTED = "HARVESTED"
    DESTROYED = "DESTROYED"


class HarvestStatus(str, Enum):
    DRYING = "DRYING"
    CURED = "CURED"
    FINISHED = "FINISHED"


class PackageStatus(str, Enum):
    TESTING = "TESTING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ON_HOLD = "ON_HOLD"
    ACTIVE = "ACTIVE"
    IN_TRANSIT = "IN_TRANSIT"
    DEPLETED = "DEPLETED"
    DESTROYED = "DESTROYED"


class ProductCategory(str, Enum):
    FLOWER = "FLOWER"
    CONCENTRATE = "CONCENTRATE"
    EDIBLE = "EDIBLE"


class LabResultOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class SaleStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class ReconciliationOutcome(str, Enum):
    MATCH = "MATCH"
    DISCREPANCY = "DISCREPANCY"


class WasteSourceType(str, Enum):
    PLANT_BATCH = "PLANT_BATCH"
    PACKAGE = "PACKAGE"


class WasteReason(str, Enum):
    MOLD = "MOLD"
    PEST = "PEST"
    FAILED_TEST = "FAILED_TEST"
    EXPIRED = "EXPIRED"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#   Principal resources carry id + created_at + updated_at + version.
#   Append-only / child records carry ONLY id + created_at.
# ---------------------------------------------------------------------------

# Principal resource: id + created_at + updated_at + version
class License(TypedDict):
    id: str
    license_number: str
    license_type: str
    status: str
    state_code: str
    expires_on: str
    daily_purchase_limit_grams: float
    created_at: str
    updated_at: str
    version: int


# Principal resource
class PlantBatch(TypedDict):
    id: str
    license_id: str
    lot_tag: str
    strain: str
    status: str
    plant_count: int
    live_plant_count: int
    planted_at: str
    created_at: str
    updated_at: str
    version: int


# Principal resource
class Harvest(TypedDict):
    id: str
    plant_batch_id: str
    license_id: str
    harvest_name: str
    status: str
    wet_weight_grams: float
    dry_weight_grams: Optional[float]
    packaged_weight_grams: float
    remaining_weight_grams: Optional[float]
    created_at: str
    updated_at: str
    version: int


# Principal resource
class Package(TypedDict):
    id: str
    harvest_id: str
    license_id: str
    package_tag: str
    product_category: str
    quantity_grams: float
    remaining_grams: float
    status: str
    lab_hold: bool
    thc_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


# Append-only record: id + created_at only (no updated_at, no version)
class LabResult(TypedDict):
    id: str
    package_id: str
    testing_license_id: str
    thc_pct: float
    pesticide_pass: bool
    overall_result: str
    tested_at: str
    created_at: str


# Principal resource
class Manifest(TypedDict):
    id: str
    origin_license_id: str
    destination_license_id: str
    status: str
    line_count: int
    total_grams: float
    departed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Child record: id + created_at only
class ManifestLine(TypedDict):
    id: str
    manifest_id: str
    package_id: str
    grams: float
    created_at: str


# Principal resource
class Customer(TypedDict):
    id: str
    medical_card_number: Optional[str]
    is_medical: bool
    birthdate: str
    created_at: str
    updated_at: str
    version: int


# Principal resource
class Sale(TypedDict):
    id: str
    retail_license_id: str
    customer_id: str
    sale_date: str
    status: str
    flower_equiv_grams: float
    created_at: str
    updated_at: str
    version: int


# Child record: id + created_at only
class SaleLine(TypedDict):
    id: str
    sale_id: str
    package_id: str
    grams: float
    flower_equiv_grams: float
    created_at: str


# Append-only record: id + created_at only
class ReconciliationCount(TypedDict):
    id: str
    package_id: str
    counted_by_user_id: str
    counted_grams: float
    expected_grams: float
    variance_grams: float
    outcome: str
    counted_at: str
    created_at: str


# Append-only record: id + created_at only
class WasteEvent(TypedDict):
    id: str
    source_type: str
    plant_batch_id: Optional[str]
    package_id: Optional[str]
    reason: str
    destroyed_grams: float
    destroyed_plant_count: int
    destroyed_at: str
    created_at: str
