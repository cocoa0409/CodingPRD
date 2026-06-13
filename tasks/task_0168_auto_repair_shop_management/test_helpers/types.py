"""Domain types: entity TypedDicts, status enums, and the role enum.

All entities in this API carry the full common-field set (id, created_at,
updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SERVICE_ADVISOR = "ServiceAdvisor"
    TECHNICIAN = "Technician"
    CUSTOMER = "Customer"
    PARTS_MANAGER = "PartsManager"
    SHOP_MANAGER = "ShopManager"


# ---------------------------------------------------------------------------
# Status enums (PRD §3 state machines)
# ---------------------------------------------------------------------------
class RepairOrderStatus(str, Enum):
    ESTIMATE = "ESTIMATE"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class LaborLineStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class PartLineStatus(str, Enum):
    QUOTED = "QUOTED"
    INSTALLED = "INSTALLED"
    RETURNED = "RETURNED"


class CoreChargeStatus(str, Enum):
    CHARGED = "CHARGED"
    CORE_RETURNED = "CORE_RETURNED"
    FORFEITED = "FORFEITED"


class InspectionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVIEWED = "REVIEWED"


class RecommendedJobStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    DEFERRED = "DEFERRED"


class SkillLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class BayType(str, Enum):
    GENERAL = "GENERAL"
    ALIGNMENT = "ALIGNMENT"
    LIFT = "LIFT"


class BillingMethod(str, Enum):
    FLAT_RATE = "FLAT_RATE"
    TIME_AND_MATERIALS = "TIME_AND_MATERIALS"


class MarkupMode(str, Enum):
    MARGINAL = "MARGINAL"
    FLAT_BRACKET = "FLAT_BRACKET"


class Severity(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 — every entity carries the full common-field set)
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    full_name: str
    phone: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    customer_id: str
    vin: str
    make: str
    model: str
    model_year: int
    odometer_miles: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    skill_level: str
    clocked_labor_line_id: Optional[str]
    last_clock_out_at: Optional[str]
    banked_flat_hours: float
    banked_actual_hours: float
    efficiency_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ServiceBay(TypedDict):
    id: str
    bay_name: str
    bay_type: str
    created_at: str
    updated_at: str
    version: int


class LaborOperation(TypedDict):
    id: str
    op_code: str
    description: str
    book_hours: float
    default_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class MarkupTier(TypedDict):
    id: str
    tier_index: int
    lower_bound_cents: int
    upper_bound_cents: Optional[int]
    markup_pct: float
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    customer_id: str
    vehicle_id: str
    bay_id: Optional[str]
    comeback_of_ro_id: Optional[str]
    is_comeback: bool
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    tax_rate: float
    labor_total_cents: int
    parts_total_cents: int
    core_deposit_total_cents: int
    tax_cents: int
    grand_total_cents: int
    approved_work_value_cents: int
    authorized_total_cents: Optional[int]
    authorized_version: Optional[int]
    closed_at: Optional[str]
    close_odometer_miles: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class LaborLine(TypedDict):
    id: str
    repair_order_id: str
    labor_operation_id: str
    technician_id: Optional[str]
    billing_method: str
    book_hours: float
    rate_cents: Optional[int]
    actual_hours: float
    open_clock_at: Optional[str]
    is_warranty: bool
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartLine(TypedDict):
    id: str
    repair_order_id: str
    part_number: str
    description: str
    quantity: int
    unit_cost_cents: int
    markup_mode: str
    has_core: bool
    core_deposit_cents: int
    is_warranty: bool
    extended_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoreCharge(TypedDict):
    id: str
    repair_order_id: str
    part_line_id: str
    deposit_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    repair_order_id: str
    technician_id: str
    items: List[dict]
    worst_severity: str
    red_item_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecommendedJob(TypedDict):
    id: str
    inspection_id: str
    repair_order_id: str
    labor_operation_id: str
    part_number: Optional[str]
    part_quantity: int
    part_unit_cost_cents: int
    has_core: bool
    core_deposit_cents: int
    estimated_value_cents: int
    severity: str
    created_labor_line_id: Optional[str]
    created_part_line_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
