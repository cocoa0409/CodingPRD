"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this domain is mutable and carries the common fields
id, created_at, updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DESIGN_CONSULTANT = "DesignConsultant"
    PROJECT_MANAGER = "ProjectManager"
    CLIENT = "Client"


class ProductCategory(str, Enum):
    PAVER = "PAVER"
    WALL_BLOCK = "WALL_BLOCK"
    FIRE_PIT = "FIRE_PIT"
    OUTDOOR_KITCHEN = "OUTDOOR_KITCHEN"


class ProductUnit(str, Enum):
    SQFT = "SQFT"
    FACE_SQFT = "FACE_SQFT"
    EACH = "EACH"
    LINEAR_FT = "LINEAR_FT"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    PENDING_APPROVALS = "PENDING_APPROVALS"
    CONTRACTED = "CONTRACTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DesignRevisionStatus(str, Enum):
    DRAFTING = "DRAFTING"
    RENDERED = "RENDERED"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"


class PermitStatus(str, Enum):
    PREPARING = "PREPARING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class HoaSubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    REJECTED = "REJECTED"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MaterialOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class WorkPhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class WorkPhaseType(str, Enum):
    EXCAVATION = "EXCAVATION"
    BASE_PREP = "BASE_PREP"
    PAVER_SET = "PAVER_SET"
    WALL_BUILD = "WALL_BUILD"
    FEATURE_INSTALL = "FEATURE_INSTALL"
    FINAL_GRADE = "FINAL_GRADE"


class DrawType(str, Enum):
    DEPOSIT = "DEPOSIT"
    PROGRESS = "PROGRESS"
    RETENTION_RELEASE = "RETENTION_RELEASE"


class DrawStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class WarrantyClaimCategory(str, Enum):
    WORKMANSHIP = "WORKMANSHIP"
    MATERIAL = "MATERIAL"
    SETTLEMENT = "SETTLEMENT"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    billing_address: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    unit: str
    unit_price_cents: int
    waste_factor: float
    coverage_per_pallet_sqft: float
    is_feature: bool
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    customer_id: str
    site_address: str
    region_code: str
    in_hoa: bool
    status: str
    permit_required: bool
    hoa_required: bool
    estimated_total_cents: int
    prompt_pay_discount_cents: int
    contract_value_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    final_billed_total_cents: int
    warranty_start_date: Optional[str]
    warranty_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict, total=False):
    id: str
    project_id: str
    product_id: str
    category: str
    measured_quantity: float
    pinned_unit_price_cents: Optional[int]
    installed_quantity: Optional[float]
    origin: str
    created_at: str
    updated_at: str
    version: int


class WorkPhase(TypedDict, total=False):
    id: str
    project_id: str
    crew_id: Optional[str]
    phase_type: str
    requires_permit: bool
    covered_line_item_ids: List[str]
    sequence_index: int
    is_final: bool
    start_date: Optional[str]
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgressDraw(TypedDict, total=False):
    id: str
    project_id: str
    work_phase_id: Optional[str]
    draw_type: str
    amount_cents: int
    expected_project_version: int
    status: str
    created_at: str
    updated_at: str
    version: int
