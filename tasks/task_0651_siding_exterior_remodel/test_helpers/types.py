"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry id, created_at, updated_at, and version
(see PRD §2.4: "No entity in this system is version-free; updated_at and
version are present on all of them.").
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    ESTIMATOR = "Estimator"
    PROJECT_MANAGER = "ProjectManager"
    HOMEOWNER_CLIENT = "HomeownerClient"
    FINANCE_OFFICER = "FinanceOfficer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ProjectWorkflowStatus(str, Enum):
    DRAFT = "DRAFT"
    MEASURED = "MEASURED"
    ESTIMATED = "ESTIMATED"
    ORDERED = "ORDERED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProjectComplianceStatus(str, Enum):
    PENDING_CLEARANCE = "PENDING_CLEARANCE"
    PERMIT_FILED = "PERMIT_FILED"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class StaffRoleCode(str, Enum):
    ESTIMATOR = "ESTIMATOR"
    PROJECT_MANAGER = "PROJECT_MANAGER"
    FINANCE_OFFICER = "FINANCE_OFFICER"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    BASELINE = "BASELINE"


class ScopeKind(str, Enum):
    SIDING = "SIDING"
    TRIM = "TRIM"
    WRAP = "WRAP"


class PermitStatus(str, Enum):
    FILED = "FILED"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"


class HOAApprovalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class MaterialOrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    BACKORDERED = "BACKORDERED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ChangeOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    NEGOTIATING = "NEGOTIATING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class WorkScheduleMilestone(str, Enum):
    WRAP_INSTALL = "WRAP_INSTALL"
    SIDING_INSTALL = "SIDING_INSTALL"
    TRIM_FINISH = "TRIM_FINISH"


class WorkScheduleStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    WEATHER_HOLD = "WEATHER_HOLD"


class ProgressDrawStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    CLAWED_BACK = "CLAWED_BACK"
    REJECTED = "REJECTED"


class WarrantyKind(str, Enum):
    LIFETIME_MATERIAL = "LIFETIME_MATERIAL"
    WORKMANSHIP = "WORKMANSHIP"


class WarrantyStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class FinancingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4)
# ---------------------------------------------------------------------------
class Project(TypedDict):
    id: str
    client_id: str
    project_manager_id: str
    property_address: str
    hoa_required: bool
    workflow_status: str
    compliance_status: str
    contract_total_cents: int
    retainage_held_cents: int
    amount_released_cents: int
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HomeownerClient(TypedDict):
    id: str
    email: str
    full_name: str
    annual_income_cents: int
    monthly_debt_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    email: str
    full_name: str
    role_code: str
    created_at: str
    updated_at: str
    version: int


class Measurement(TypedDict):
    id: str
    project_id: str
    estimator_id: str
    gross_wall_sqft: float
    opening_sqft: float
    linear_trim_ft: float
    net_siding_sqft: float
    color_code: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    project_id: str
    measurement_id: str
    status: str
    waste_factor_pct: float
    line_subtotal_cents: int
    tax_cents: int
    estimate_total_cents: int
    created_at: str
    updated_at: str
    version: int


class EstimateLineItem(TypedDict):
    id: str
    estimate_id: str
    scope_kind: str
    quantity: float
    unit_price_cents: int
    extended_cents: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    project_id: str
    jurisdiction: str
    status: str
    permit_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HOAApproval(TypedDict):
    id: str
    project_id: str
    status: str
    reviewed_color_code: str
    created_at: str
    updated_at: str
    version: int


class MaterialOrder(TypedDict):
    id: str
    project_id: str
    estimate_id: str
    status: str
    ordered_sqft: float
    delivery_eta_iso: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    target_line_item_id: str
    supersedes_change_order_id: Optional[str]
    status: str
    delta_cents: int
    pm_approved: bool
    client_approved: bool
    created_at: str
    updated_at: str
    version: int


class WorkSchedule(TypedDict):
    id: str
    project_id: str
    crew_id: str
    milestone: str
    window_start_iso: str
    window_end_iso: str
    forecast_wind_mph: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    max_wind_mph: float
    created_at: str
    updated_at: str
    version: int


class ProgressDraw(TypedDict):
    id: str
    project_id: str
    work_schedule_id: str
    status: str
    approved_by_staff_id: Optional[str]
    milestone_pct: float
    gross_amount_cents: int
    retainage_cents: int
    net_released_cents: int
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict):
    id: str
    project_id: str
    warranty_kind: str
    status: str
    workmanship_years: int
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict):
    id: str
    project_id: str
    client_id: str
    requested_amount_cents: int
    term_months: int
    status: str
    monthly_payment_cents: int
    dti_ratio: float
    created_at: str
    updated_at: str
    version: int
