"""Domain types: entity TypedDicts, status enums, role enum for the Glass & Mirror Shop API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum (PRD §2.1 — five roles spelled exactly)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    ESTIMATOR = "Estimator"
    CONTRACTOR = "Contractor"
    FABRICATOR = "Fabricator"
    SCHEDULER = "Scheduler"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    SUSPENDED = "SUSPENDED"


class AccountTier(str, Enum):
    WALK_IN = "WALK_IN"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ORDERED = "ORDERED"


class LineItemStatus(str, Enum):
    SPEC = "SPEC"
    FABRICATING = "FABRICATING"
    FABRICATED = "FABRICATED"
    INSTALLED = "INSTALLED"
    BROKEN = "BROKEN"


class ProductType(str, Enum):
    SHOWER_ENCLOSURE = "SHOWER_ENCLOSURE"
    STOREFRONT = "STOREFRONT"
    CUSTOM_MIRROR = "CUSTOM_MIRROR"
    TABLETOP = "TABLETOP"


class GlassType(str, Enum):
    ANNEALED = "ANNEALED"
    TEMPERED = "TEMPERED"
    LAMINATED = "LAMINATED"
    INSULATED = "INSULATED"


class EdgeWork(str, Enum):
    NONE = "NONE"
    POLISHED = "POLISHED"
    BEVELED = "BEVELED"


class JobStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FabricationStatus(str, Enum):
    PENDING = "PENDING"
    IN_FABRICATION = "IN_FABRICATION"
    COMPLETE = "COMPLETE"
    REOPENED = "REOPENED"


class InstallStatus(str, Enum):
    NOT_READY = "NOT_READY"
    READY = "READY"
    SCHEDULED = "SCHEDULED"
    INSTALLED = "INSTALLED"
    ON_HOLD = "ON_HOLD"


class BatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimType(str, Enum):
    BREAKAGE = "BREAKAGE"
    WARRANTY_DEFECT = "WARRANTY_DEFECT"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RemakeStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"


# --------------------------------------------------------------------------
# Entity TypedDicts — every entity carries common fields (id, created_at,
# updated_at, version) per PRD §2.4.
# --------------------------------------------------------------------------
class ContractorAccount(TypedDict):
    id: str
    company_name: str
    tier: str
    credit_limit_cents: int
    credit_used_cents: int
    available_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    contractor_account_id: str
    status: str
    revision_number: int
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    quoted_lead_days: Optional[int]
    valid_until: Optional[str]
    ordered_job_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict):
    id: str
    quote_id: str
    product_type: str
    glass_type: str
    thickness_mm: int
    width_in: float
    height_in: float
    quantity: int
    edge_work: str
    requires_safety_glazing: bool
    billable_sqft: float
    unit_price_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict):
    id: str
    quote_id: str
    contractor_account_id: str
    status: str
    fabrication_status: str
    install_status: str
    job_fab_sqft: float
    committed_lead_days: int
    credit_hold_cents: int
    final_total_cents: int
    created_at: str
    updated_at: str
    version: int


class TemperingFurnace(TypedDict):
    id: str
    name: str
    max_batch_sqft: float
    cooldown_minutes: int
    reserved_sqft: float
    created_at: str
    updated_at: str
    version: int


class TemperingBatch(TypedDict):
    id: str
    furnace_id: str
    job_id: str
    scheduled_start: str
    scheduled_end: str
    total_sqft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallCrew(TypedDict):
    id: str
    name: str
    certified_products: List[str]
    created_at: str
    updated_at: str
    version: int


class InstallAppointment(TypedDict):
    id: str
    crew_id: str
    job_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimReport(TypedDict):
    id: str
    job_id: str
    line_item_id: str
    claim_type: str
    cause: str
    billable_to_contractor: bool
    status: str
    remake_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemakeOrder(TypedDict):
    id: str
    claim_report_id: str
    job_id: str
    line_item_id: str
    billable_to_contractor: bool
    remake_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
