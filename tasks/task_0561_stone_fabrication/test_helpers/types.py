"""Domain types: entity TypedDicts, status enums, role enum for the Stone Fabrication API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    SALES_REP = "SalesRep"
    FABRICATOR = "Fabricator"
    INSTALLER = "Installer"


# --- Shared value enums ---
class MaterialGrade(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    EXOTIC = "EXOTIC"


class EdgeProfile(str, Enum):
    EASED = "EASED"
    BEVELED = "BEVELED"
    BULLNOSE = "BULLNOSE"
    OGEE = "OGEE"


class CutoutType(str, Enum):
    SINK = "SINK"
    FAUCET = "FAUCET"
    COOKTOP = "COOKTOP"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"


class ClaimType(str, Enum):
    SEAL = "SEAL"
    CHIP = "CHIP"
    CRACK = "CRACK"


class Resolution(str, Enum):
    SEAL_REPAIR = "SEAL_REPAIR"
    REPLACEMENT = "REPLACEMENT"
    REJECTED = "REJECTED"


# --- Status enums ---
class ProjectStatus(str, Enum):
    INTAKE = "INTAKE"
    IN_PRODUCTION = "IN_PRODUCTION"
    ON_HOLD = "ON_HOLD"
    INSTALLED = "INSTALLED"
    CLOSED = "CLOSED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"


class QuoteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    MEASURED = "MEASURED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class SlabStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"


class FabricationOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CUTTING = "CUTTING"
    RECUTTING = "RECUTTING"
    QC_PASSED = "QC_PASSED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class InstallJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class PaymentTxnStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts ---
# Entities that can be modified after creation carry id + created_at + updated_at + version.
class Project(TypedDict):
    id: str
    customer_name: str
    address: str
    material_grade: str
    status: str
    payment_status: str
    quoted_total_cents: int
    final_invoice_cents: Optional[int]
    amount_paid_cents: int
    balance_due_cents: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    project_id: str
    est_sqft: float
    material_grade: str
    edge_profile: str
    edge_linear_ft: float
    sink_count: int
    faucet_count: int
    cooktop_count: int
    subtotal_cents: int
    quote_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Template(TypedDict):
    id: str
    project_id: str
    measured_sqft: float
    edge_profile: str
    edge_linear_ft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Slab(TypedDict):
    id: str
    slab_label: str
    material_grade: str
    nominal_sqft: float
    status: str
    reserved_sqft: float
    remaining_sqft: float
    created_at: str
    updated_at: str
    version: int


class FabricationOrder(TypedDict):
    id: str
    project_id: str
    template_id: str
    slab_id: str
    bay_id: str
    scheduled_start: str
    scheduled_end: str
    pieces: list
    actual_consumed_sqft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallJob(TypedDict):
    id: str
    project_id: str
    fabrication_order_id: str
    crew_id: str
    install_date: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    project_id: str
    amount_cents: int
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    description: str
    delta_cents: int
    reopens_template: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    install_job_id: str
    claim_type: str
    description: str
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable snapshots carry ONLY id + created_at (no updated_at, no version).
class Cutout(TypedDict):
    id: str
    template_id: str
    cutout_type: str
    charge_cents: int
    created_at: str


class Remnant(TypedDict):
    id: str
    slab_id: str
    area_sqft: float
    status: str
    created_at: str


class Bay(TypedDict):
    id: str
    name: str
    created_at: str


class Crew(TypedDict):
    id: str
    name: str
    created_at: str
