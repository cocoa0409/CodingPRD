"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain are mutable and therefore carry the common fields
id, created_at, updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    LIGHTING_DESIGNER = "LightingDesigner"
    INSTALL_TECH = "InstallTech"
    CONTROL_PROGRAMMER = "ControlProgrammer"
    CUSTOMER = "Customer"
    OPERATIONS_ADMIN = "OperationsAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ProjectDesignStatus(str, Enum):
    DRAFT = "DRAFT"
    ZONED = "ZONED"
    DESIGN_LOCKED = "DESIGN_LOCKED"


class ProjectCommercialStatus(str, Enum):
    PRE_QUOTE = "PRE_QUOTE"
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    INSTALLED = "INSTALLED"
    CLOSED = "CLOSED"


class TransformerStatus(str, Enum):
    STAGED = "STAGED"
    ENERGIZED = "ENERGIZED"
    DECOMMISSIONED = "DECOMMISSIONED"


class FixtureCategory(str, Enum):
    PATH = "PATH"
    SPOT = "SPOT"
    WELL = "WELL"
    STEP = "STEP"
    AUDIO = "AUDIO"
    SECURITY = "SECURITY"


class FixtureStatus(str, Enum):
    PLANNED = "PLANNED"
    INSTALLED = "INSTALLED"
    FAILED = "FAILED"
    REMOVED = "REMOVED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class InstallWiringStatus(str, Enum):
    PENDING = "PENDING"
    WIRED = "WIRED"


class InstallFixturesStatus(str, Enum):
    PENDING = "PENDING"
    MOUNTED = "MOUNTED"


class InstallJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    ENERGIZED = "ENERGIZED"
    CANCELLED = "CANCELLED"


class ScheduleProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ServicePlanTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class ServicePlanStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    ADJUSTING = "ADJUSTING"
    CANCELLED = "CANCELLED"


class ServiceVisitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ROUTED = "ROUTED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class CrewRouteStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class WarrantyCreditVariant(str, Enum):
    FULL = "FULL"
    DEPRECIATED = "DEPRECIATED"


class AddOnKind(str, Enum):
    AUDIO = "AUDIO"
    SECURITY = "SECURITY"


class AddOnStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all common_fields: true)
# ---------------------------------------------------------------------------
class LightingProject(TypedDict):
    id: str
    customer_id: str
    property_address: str
    design_status: str
    commercial_status: str
    fixture_count: int
    total_committed_load_va: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Transformer(TypedDict):
    id: str
    project_id: str
    model_code: str
    rated_capacity_va: int
    usable_capacity_va: int
    committed_load_va: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict):
    id: str
    project_id: str
    transformer_id: str
    label: str
    zone_load_va: int
    created_at: str
    updated_at: str
    version: int


class Fixture(TypedDict):
    id: str
    zone_id: Optional[str]
    project_id: str
    model_code: str
    category: str
    wattage_w: int
    purchase_price_cents: int
    warranty_months: int
    installed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    project_id: str
    night_demo_requested: bool
    night_demo_at: Optional[str]
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    grand_total_cents: int
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QuoteLine(TypedDict):
    id: str
    quote_id: str
    model_code: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class InstallJob(TypedDict):
    id: str
    project_id: str
    quote_id: str
    wiring_status: str
    fixtures_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScheduleProgram(TypedDict):
    id: str
    project_id: str
    scene_label: str
    window_start_min: int
    window_end_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServicePlan(TypedDict):
    id: str
    project_id: str
    tier: str
    annual_fee_cents: int
    refundable: bool
    activated_at: Optional[str]
    season_cycle_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    service_plan_id: str
    project_id: str
    visit_date: str
    window_start_min: int
    window_end_min: int
    route_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewRoute(TypedDict):
    id: str
    technician_id: str
    route_date: str
    visit_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    fixture_id: str
    project_id: str
    reason: str
    credit_variant: Optional[str]
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOnModule(TypedDict):
    id: str
    project_id: str
    zone_id: Optional[str]
    kind: str
    power_draw_va: int
    status: str
    created_at: str
    updated_at: str
    version: int
