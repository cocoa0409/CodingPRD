"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class RetailerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CategoryStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    ARCHIVED = "ARCHIVED"


class CategoryRole(str, Enum):
    DESTINATION = "DESTINATION"
    ROUTINE = "ROUTINE"
    CONVENIENCE = "CONVENIENCE"
    SEASONAL = "SEASONAL"


class ProductStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    LISTED = "LISTED"
    DISCONTINUING = "DISCONTINUING"
    DELISTED = "DELISTED"


class PlanogramVariant(str, Enum):
    BASE = "BASE"
    CLUSTER_A = "CLUSTER_A"
    CLUSTER_B = "CLUSTER_B"


class PlanogramStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class DosFlag(str, Enum):
    UNDERSTOCK = "UNDERSTOCK"
    OK = "OK"
    OVERSTOCK = "OVERSTOCK"


class StoreCluster(str, Enum):
    BASE = "BASE"
    CLUSTER_A = "CLUSTER_A"
    CLUSTER_B = "CLUSTER_B"


class AuditStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCORED = "SCORED"
    REJECTED = "REJECTED"


class ComplianceOutcome(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class FundingDealStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class CoiFlag(str, Enum):
    NONE = "NONE"
    CAPTAIN_SELF_DEALING = "CAPTAIN_SELF_DEALING"
    CAPTAIN_BLOCKING_RIVAL = "CAPTAIN_BLOCKING_RIVAL"


class ResetProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ResetAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RETAILER_ADMIN = "RetailerAdmin"
    CATEGORY_MANAGER = "CategoryManager"
    CATEGORY_CAPTAIN = "CategoryCaptain"
    FIELD_AUDITOR = "FieldAuditor"
    AUDIT_REVIEWER = "AuditReviewer"
    RESET_COORDINATOR = "ResetCoordinator"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities here carry common_fields: true — they all
# expose id + created_at + updated_at + version).
# ---------------------------------------------------------------------------

class Retailer(TypedDict, total=False):
    id: str
    name: str
    status: str
    compliance_threshold_pct: int
    created_at: str
    updated_at: str
    version: int


class Category(TypedDict, total=False):
    id: str
    retailer_id: str
    code: str
    role: str
    annual_sales_cents: int
    total_linear_feet: int
    status: str
    active_planogram_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    retailer_id: str
    name: str
    is_captain: bool
    captain_category_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    retailer_id: str
    category_id: str
    supplier_id: str
    sku: str
    width_in: float
    unit_cost_cents: int
    weekly_demand_units: int
    status: str
    discontinuation_effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Planogram(TypedDict, total=False):
    id: str
    category_id: str
    name: str
    variant: str
    status: str
    version_note: Optional[str]
    total_facings: int
    total_capacity_units: int
    shelf_utilization_pct: float
    submitted_by_captain_supplier_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanogramLine(TypedDict, total=False):
    id: str
    planogram_id: str
    product_id: str
    position_index: int
    facings: int
    capacity_units: int
    days_of_supply: float
    dos_flag: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    retailer_id: str
    store_code: str
    cluster: str
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict, total=False):
    id: str
    store_id: str
    planogram_id: str
    photo_url: str
    submitted_by_role: str
    status: str
    matched_facings: Optional[int]
    total_facings_expected: Optional[int]
    compliance_score_pct: Optional[int]
    compliance_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingDeal(TypedDict, total=False):
    id: str
    retailer_id: str
    category_id: str
    supplier_id: str
    amount_cents: int
    starts_at: str
    ends_at: str
    status: str
    coi_flag: str
    created_at: str
    updated_at: str
    version: int


class ResetProject(TypedDict, total=False):
    id: str
    category_id: str
    planogram_id: str
    store_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    labor_hours_estimated: float
    created_at: str
    updated_at: str
    version: int


class ResetCrew(TypedDict, total=False):
    id: str
    retailer_id: str
    name: str
    max_concurrent_projects: int
    created_at: str
    updated_at: str
    version: int


class ResetAssignment(TypedDict, total=False):
    id: str
    reset_project_id: str
    crew_id: str
    assigned_start: str
    assigned_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
