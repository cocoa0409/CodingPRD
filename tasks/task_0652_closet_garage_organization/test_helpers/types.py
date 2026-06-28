"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    DESIGNER = "Designer"
    SCHEDULER = "Scheduler"
    MANUFACTURING_OPS = "ManufacturingOps"
    PLATFORM_ADMIN = "PlatformAdmin"


class Region(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


class RoomType(str, Enum):
    REACH_IN_CLOSET = "REACH_IN_CLOSET"
    WALK_IN_CLOSET = "WALK_IN_CLOSET"
    GARAGE = "GARAGE"
    PANTRY = "PANTRY"
    HOME_OFFICE = "HOME_OFFICE"


class ProjectStatus(str, Enum):
    LEAD = "LEAD"
    DESIGNING = "DESIGNING"
    QUOTED = "QUOTED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    IN_MANUFACTURE = "IN_MANUFACTURE"
    READY_TO_INSTALL = "READY_TO_INSTALL"
    INSTALLING = "INSTALLING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DesignConsultStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RENDERED = "RENDERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MaterialGrade(str, Enum):
    MELAMINE = "MELAMINE"
    LAMINATE = "LAMINATE"
    WOOD = "WOOD"
    PREMIUM_WOOD = "PREMIUM_WOOD"


class ComponentType(str, Enum):
    SHELF = "SHELF"
    DRAWER = "DRAWER"
    ROD = "ROD"
    CABINET = "CABINET"
    PANEL = "PANEL"
    ACCESSORY = "ACCESSORY"


class ComponentConfigStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class DepositStatus(str, Enum):
    PENDING = "PENDING"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class ManufactureOrderStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    INSTALLED = "INSTALLED"


class InstallSchedStatus(str, Enum):
    PROPOSED = "PROPOSED"
    BOOKED = "BOOKED"
    RESCHEDULING = "RESCHEDULING"
    CANCELLED = "CANCELLED"


class InstallCompletionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class ChangeType(str, Enum):
    CONFIG_REVISION = "CONFIG_REVISION"
    SCHEDULE_CHANGE = "SCHEDULE_CHANGE"


class ChangeOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


class DefectType(str, Enum):
    HARDWARE = "HARDWARE"
    FINISH = "FINISH"
    FIT = "FIT"
    STRUCTURAL = "STRUCTURAL"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ADJUSTMENT_SCHEDULED = "ADJUSTMENT_SCHEDULED"
    REPLACEMENT_ORDERED = "REPLACEMENT_ORDERED"
    RESOLVED = "RESOLVED"


class FinancingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    FUNDED = "FUNDED"


# All entities carry common fields (id, created_at, updated_at, version).

class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    zip_code: str
    install_region: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    customer_id: str
    room_type: str
    status: str
    financing_application_id: Optional[str]
    accepted_quote_id: Optional[str]
    balance_due_cents: int
    install_region: str
    created_at: str
    updated_at: str
    version: int


class DesignConsult(TypedDict):
    id: str
    project_id: str
    designer_user_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    rendering_url: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpaceMeasure(TypedDict):
    id: str
    project_id: str
    wall_count: int
    linear_feet: float
    ceiling_height_in: float
    confirmed: bool
    created_at: str
    updated_at: str
    version: int


class ComponentConfig(TypedDict):
    id: str
    project_id: str
    space_measure_id: str
    material_grade: str
    line_items: List[dict]
    status: str
    total_units: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    project_id: str
    component_config_id: str
    status: str
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int
    promo_code: Optional[str]
    issued_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict):
    id: str
    project_id: str
    quote_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ManufactureOrder(TypedDict):
    id: str
    project_id: str
    quote_id: str
    status: str
    lead_time_days: int
    promised_ready_date: Optional[str]
    started_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    crew_name: str
    region: str
    daily_capacity_units: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class InstallJob(TypedDict):
    id: str
    project_id: str
    manufacture_order_id: str
    crew_id: str
    window_start: str
    window_end: str
    sched_status: str
    completion_status: str
    units_booked: int
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    base_quote_id: str
    change_type: str
    revised_config_id: Optional[str]
    status: str
    delta_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    project_id: str
    install_job_id: str
    defect_type: str
    status: str
    covered: bool
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict):
    id: str
    project_id: str
    quote_id: str
    requested_amount_cents: int
    term_months: int
    status: str
    approved_amount_cents: int
    monthly_payment_cents: int
    created_at: str
    updated_at: str
    version: int
