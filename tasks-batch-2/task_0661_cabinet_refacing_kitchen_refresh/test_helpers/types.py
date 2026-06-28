"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the full common-field set (id, created_at,
updated_at, version), per the PRD's common-resource-properties section.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SALES_REP = "SalesRep"
    SCHEDULER = "Scheduler"
    INSTALL_CREW = "InstallCrew"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---- Status enums ----

class ProjectStatus(str, Enum):
    LEAD = "LEAD"
    MEASURED = "MEASURED"
    QUOTED = "QUOTED"
    SOLD = "SOLD"
    IN_PRODUCTION = "IN_PRODUCTION"
    INSTALLED = "INSTALLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class MeasureStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    REVISING = "REVISING"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    DECLINED = "DECLINED"


class QuoteScope(str, Enum):
    PAINT = "PAINT"
    REFACE = "REFACE"
    REDOOR = "REDOOR"


class FinishCode(str, Enum):
    LAMINATE = "LAMINATE"
    THERMOFOIL = "THERMOFOIL"
    WOOD_VENEER = "WOOD_VENEER"
    SOLID_WOOD = "SOLID_WOOD"
    PAINT = "PAINT"


class AddOnKind(str, Enum):
    HARDWARE = "HARDWARE"
    COUNTERTOP = "COUNTERTOP"


class AddOnStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REMOVED = "REMOVED"


class ChangeOrderStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class MaterialOrderStatus(str, Enum):
    PLACED = "PLACED"
    READY = "READY"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class InstallJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class FinancingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


# ---- Entity TypedDicts (all carry full common-field set) ----

class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    annual_income_cents: int
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    customer_id: str
    address_line: str
    status: str
    active_quote_id: Optional[str]
    linear_feet: Optional[float]
    door_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Measure(TypedDict):
    id: str
    project_id: str
    scheduled_for: str
    status: str
    linear_feet: Optional[float]
    door_count: Optional[int]
    door_style: Optional[str]
    finish_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    project_id: str
    measure_id: str
    scope: str
    status: str
    estimate_total_cents: int
    firm_total_cents: Optional[int]
    addons_total_cents: int
    expires_at: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    quote_id: str
    kind: str
    unit_price_cents: int
    quantity: float
    status: str
    price_cents: int
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    quote_id: str
    delta_linear_feet: float
    delta_door_count: int
    rush: bool
    status: str
    price_delta_cents: Optional[int]
    lead_time_delta_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MaterialOrder(TypedDict):
    id: str
    project_id: str
    quote_id: str
    status: str
    base_lead_time_days: int
    ready_at: str
    lead_extension_days: int
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    daily_job_capacity: int
    skill_finishes: List[str]
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class InstallJob(TypedDict):
    id: str
    project_id: str
    material_order_id: str
    crew_id: str
    window_start: str
    window_end: str
    status: str
    install_day: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    project_id: str
    description: str
    status: str
    covered: bool
    filed_at: str
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict):
    id: str
    project_id: str
    customer_id: str
    amount_cents: int
    term_months: int
    status: str
    monthly_payment_cents: int
    dti_ratio: float
    created_at: str
    updated_at: str
    version: int
