"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model and lifecycle workflows. Generic envelope
types live in the framework and are not redeclared here.

common-field branching (PRD §2.4): Project, Customer, SiteMeasure, DesignLayout,
BasePrepScope, Quote, Crew, InstallJob, WarrantyPlan, and Callback carry id,
created_at, updated_at, and version. TurfProduct, InfillProduct, and Payment are
exceptions that carry only id and created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ────────────────────────────────────────────────────────────
class ProjectWorkflowStatus(str, Enum):
    DRAFT = "DRAFT"
    MEASURED = "MEASURED"
    DESIGNED = "DESIGNED"
    QUOTED = "QUOTED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    SCHEDULED = "SCHEDULED"
    INSTALLED = "INSTALLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProjectFinanceStatus(str, Enum):
    UNBILLED = "UNBILLED"
    DEPOSIT_DUE = "DEPOSIT_DUE"
    DEPOSIT_SETTLED = "DEPOSIT_SETTLED"
    BALANCE_DUE = "BALANCE_DUE"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class Variant(str, Enum):
    STANDARD = "STANDARD"
    PET = "PET"
    PLAYGROUND = "PLAYGROUND"
    PUTTING_GREEN = "PUTTING_GREEN"


class SiteMeasureStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"


class DesignLayoutStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DrainageTier(str, Enum):
    NONE = "NONE"
    FRENCH_DRAIN = "FRENCH_DRAIN"
    DRAINAGE_PANEL = "DRAINAGE_PANEL"


class BasePrepScopeStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REVISED = "REVISED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class InstallJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class WarrantyTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class WarrantyStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class CallbackReason(str, Enum):
    SEAM_LIFT = "SEAM_LIFT"
    INFILL_MIGRATION = "INFILL_MIGRATION"
    DRAINAGE = "DRAINAGE"
    WRINKLE = "WRINKLE"
    PET_ODOR = "PET_ODOR"
    OTHER = "OTHER"


class CallbackStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class InfillMaterial(str, Enum):
    SILICA = "SILICA"
    ACRYLIC_COATED = "ACRYLIC_COATED"
    ZEOLITE = "ZEOLITE"
    RUBBER = "RUBBER"
    CORK = "CORK"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    SALES_REP = "SalesRep"
    SCHEDULER = "Scheduler"
    CUSTOMER = "Customer"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
# common_fields: true
class Project(TypedDict):
    id: str
    customer_id: str
    site_address: str
    workflow_status: str
    finance_status: str
    variant: Optional[str]
    billable_area_sqft: float
    contract_total_cents: int
    deposit_paid_cents: int
    balance_paid_cents: int
    amount_refunded_cents: int
    outstanding_balance_cents: int
    open_callback_count: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class SiteMeasure(TypedDict):
    id: str
    project_id: str
    gross_area_sqft: float
    obstruction_area_sqft: float
    longest_run_ft: float
    slope_pct: float
    soil_drains_freely: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DesignLayout(TypedDict):
    id: str
    project_id: str
    site_measure_id: str
    turf_product_id: str
    infill_product_id: str
    variant: str
    waste_factor_pct: float
    net_area_sqft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BasePrepScope(TypedDict):
    id: str
    project_id: str
    design_layout_id: str
    base_depth_in: float
    drainage_tier: str
    excavation_cost_cents: int
    drainage_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    project_id: str
    design_layout_id: str
    base_prep_scope_id: str
    promo_code: Optional[str]
    deposit_pct: float
    material_subtotal_cents: int
    base_prep_subtotal_cents: int
    variant_surcharge_cents: int
    discount_cents: int
    subtotal_cents: int
    total_cents: int
    deposit_amount_cents: int
    variant_kind: str
    status: str
    superseded_by_quote_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    daily_capacity_sqft: float
    certified_putting: bool
    certified_playground: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class InstallJob(TypedDict):
    id: str
    project_id: str
    crew_id: str
    scheduled_start: str
    scheduled_end: str
    install_area_sqft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyPlan(TypedDict):
    id: str
    project_id: str
    tier: str
    coverage_months: int
    maintenance_visits_per_year: int
    start_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Callback(TypedDict):
    id: str
    project_id: str
    warranty_plan_id: Optional[str]
    reason: str
    billable: bool
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — only id + created_at
class TurfProduct(TypedDict):
    id: str
    sku: str
    name: str
    pile_height_mm: float
    price_per_sqft_cents: int
    roll_width_ft: float
    pet_approved: bool
    playground_rated: bool
    putting_rated: bool
    active: bool
    created_at: str


class InfillProduct(TypedDict):
    id: str
    sku: str
    name: str
    material: str
    price_per_sqft_cents: int
    coverage_lbs_per_sqft: float
    antimicrobial: bool
    nonabrasive: bool
    active: bool
    created_at: str


class Payment(TypedDict):
    id: str
    project_id: str
    kind: str
    amount_cents: int
    status: str
    created_at: str
