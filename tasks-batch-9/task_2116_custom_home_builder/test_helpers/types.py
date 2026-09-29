"""Domain types for the Custom Home Builder API: status enums and entity shapes.

Every entity in this system carries `id`, `created_at`, `updated_at` and
`version`, so every TypedDict below lists all four.
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROJECT_MANAGER = "ProjectManager"
    ESTIMATOR = "Estimator"
    CONTROLLER = "Controller"
    CLIENT = "Client"
    LENDER = "Lender"
    SUBCONTRACTOR = "Subcontractor"


class StaffFunction(str, Enum):
    PROJECT_MANAGER = "PROJECT_MANAGER"
    ESTIMATOR = "ESTIMATOR"
    CONTROLLER = "CONTROLLER"


class Trade(str, Enum):
    SITEWORK = "SITEWORK"
    CONCRETE = "CONCRETE"
    FRAMING = "FRAMING"
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    DRYWALL = "DRYWALL"
    FINISH_CARPENTRY = "FINISH_CARPENTRY"
    PAINT = "PAINT"
    LANDSCAPE = "LANDSCAPE"


# ─── Project ──────────────────────────────────────────────────────────────
class ContractType(str, Enum):
    FIXED_PRICE = "FIXED_PRICE"
    COST_PLUS = "COST_PLUS"


class ProjectStatus(str, Enum):
    PLANNING = "PLANNING"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    SUBSTANTIAL_COMPLETION = "SUBSTANTIAL_COMPLETION"
    FINAL_ACCEPTED = "FINAL_ACCEPTED"


class BudgetPosture(str, Enum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    ALLOWANCE_OVERRUN = "ALLOWANCE_OVERRUN"
    OVER_GMP = "OVER_GMP"


# ─── Allowance book ───────────────────────────────────────────────────────
class AllowanceCategory(str, Enum):
    FLOORING = "FLOORING"
    CABINETRY = "CABINETRY"
    APPLIANCES = "APPLIANCES"
    PLUMBING_FIXTURES = "PLUMBING_FIXTURES"
    LIGHTING = "LIGHTING"
    COUNTERTOPS = "COUNTERTOPS"
    LANDSCAPE = "LANDSCAPE"


class AllowanceItemStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    SELECTED = "SELECTED"
    LOCKED = "LOCKED"
    RECONCILED = "RECONCILED"


class SelectionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


# ─── Change orders ────────────────────────────────────────────────────────
class ChangeOrderOrigin(str, Enum):
    CLIENT_REQUEST = "CLIENT_REQUEST"
    FIELD_CONDITION = "FIELD_CONDITION"
    ALLOWANCE_OVERAGE = "ALLOWANCE_OVERAGE"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


# ─── Schedule ─────────────────────────────────────────────────────────────
class ScheduleTaskStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


# ─── Cost and draws ───────────────────────────────────────────────────────
class CostEntryType(str, Enum):
    SUBCONTRACT_INVOICE = "SUBCONTRACT_INVOICE"
    MATERIAL = "MATERIAL"
    LABOR = "LABOR"
    ALLOWANCE_ACTUAL = "ALLOWANCE_ACTUAL"
    CHANGE_ORDER_WORK = "CHANGE_ORDER_WORK"


class CostEntryStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INCLUDED_IN_DRAW = "INCLUDED_IN_DRAW"
    PAID = "PAID"


class DrawRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    LENDER_REVIEW = "LENDER_REVIEW"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    RETURNED = "RETURNED"
    FUNDED = "FUNDED"
    VOIDED = "VOIDED"


class WaiverCompliance(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"


class WaiverType(str, Enum):
    CONDITIONAL_PROGRESS = "CONDITIONAL_PROGRESS"
    UNCONDITIONAL_PROGRESS = "UNCONDITIONAL_PROGRESS"
    CONDITIONAL_FINAL = "CONDITIONAL_FINAL"
    UNCONDITIONAL_FINAL = "UNCONDITIONAL_FINAL"


class LienWaiverStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


# ─── Punch list and warranty ──────────────────────────────────────────────
class DefectPhase(str, Enum):
    PUNCH = "PUNCH"
    WARRANTY = "WARRANTY"


class DefectSeverity(str, Enum):
    COSMETIC = "COSMETIC"
    FUNCTIONAL = "FUNCTIONAL"
    LIFE_SAFETY = "LIFE_SAFETY"


class DefectCategory(str, Enum):
    WORKMANSHIP = "WORKMANSHIP"
    MATERIAL_DEFECT = "MATERIAL_DEFECT"
    SYSTEMS = "SYSTEMS"
    HOMEOWNER_DAMAGE = "HOMEOWNER_DAMAGE"
    NORMAL_WEAR = "NORMAL_WEAR"


class CoverageAnchor(str, Enum):
    NONE = "NONE"
    WHOLE_HOUSE = "WHOLE_HOUSE"
    TRADE = "TRADE"


class CoverageResult(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    COVERED = "COVERED"
    OUT_OF_COVERAGE = "OUT_OF_COVERAGE"
    EXCLUDED = "EXCLUDED"


class DefectStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    DENIED = "DENIED"
    WAIVED = "WAIVED"


class PhotoVisibility(str, Enum):
    INTERNAL = "INTERNAL"
    CLIENT_PORTAL = "CLIENT_PORTAL"


# ─── Entity shapes ────────────────────────────────────────────────────────
class Client(TypedDict):
    id: str
    full_name: str
    email: str
    portal_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Lender(TypedDict):
    id: str
    name: str
    retainage_pct: float
    max_cumulative_draw_pct: float
    review_window_days: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    full_name: str
    staff_function: str
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict):
    id: str
    company_name: str
    trade: str
    lead_time_days: int
    crew_capacity: int
    waiver_required: bool
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    client_id: str
    lender_id: Optional[str]
    address: str
    contract_type: str
    base_contract_amount: float
    builder_fee_pct: Optional[float]
    gmp_cap: Optional[float]
    target_substantial_completion_date: str
    status: str
    budget_posture: str
    approved_change_order_total: float
    allowance_variance_total: float
    contract_sum_current: float
    cost_to_date: float
    eligible_cost_pool: float
    pending_draw_amount: float
    funded_to_date: float
    retainage_held: float
    construction_started_at: Optional[str]
    substantial_completion_at: Optional[str]
    final_accepted_at: Optional[str]
    warranty_starts_at: Optional[str]
    warranty_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllowanceItem(TypedDict):
    id: str
    project_id: str
    category: str
    allowance_amount: float
    selection_deadline: str
    status: str
    selected_selection_id: Optional[str]
    provisional_variance_amount: float
    final_variance_amount: Optional[float]
    reconciled_amount: Optional[float]
    material_lead_time_days: Optional[int]
    locked_at: Optional[str]
    frozen_at: Optional[str]
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Selection(TypedDict):
    id: str
    allowance_item_id: str
    vendor_name: str
    vendor_quote_amount: float
    freight_amount: float
    install_amount: float
    lead_time_days: int
    selection_total: float
    status: str
    decided_at: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    source_allowance_item_id: Optional[str]
    priced_by_staff_id: Optional[str]
    submitted_by_staff_id: Optional[str]
    origin: str
    scope_description: str
    direct_cost: float
    schedule_impact_days: int
    markup_rate_applied: Optional[float]
    contingency_rate_applied: Optional[float]
    priced_amount: Optional[float]
    status: str
    revision_count: int
    revision_note: Optional[str]
    void_reason: Optional[str]
    priced_at: Optional[str]
    submitted_at: Optional[str]
    client_response_due_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScheduleTask(TypedDict):
    id: str
    project_id: str
    subcontractor_id: str
    predecessor_task_id: Optional[str]
    driving_allowance_item_id: Optional[str]
    task_name: str
    planned_start: str
    planned_finish: str
    lag_days: int
    exclusive_use: bool
    status: str
    material_ready_at: Optional[str]
    actual_start: Optional[str]
    actual_finish: Optional[str]
    delay_days: int
    float_days: Optional[int]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostEntry(TypedDict):
    id: str
    project_id: str
    subcontractor_id: Optional[str]
    source_allowance_item_id: Optional[str]
    draw_request_id: Optional[str]
    approved_by_staff_id: Optional[str]
    entry_type: str
    cost_code: str
    amount: float
    incurred_at: str
    status: str
    approved_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DrawRequest(TypedDict):
    id: str
    project_id: str
    submitted_by_staff_id: Optional[str]
    period_start: str
    period_end: str
    status: str
    waiver_compliance: str
    requested_amount: float
    retainage_amount: float
    net_funding_amount: float
    included_cost_entry_count: int
    required_waiver_count: int
    verified_waiver_count: int
    lender_decision_due_at: Optional[str]
    condition_note: Optional[str]
    void_reason: Optional[str]
    submitted_at: Optional[str]
    conditionally_approved_at: Optional[str]
    returned_at: Optional[str]
    funded_at: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LienWaiver(TypedDict):
    id: str
    draw_request_id: str
    subcontractor_id: str
    required_waiver_type: str
    required_amount: float
    waiver_type: Optional[str]
    through_date: Optional[str]
    amount_covered: Optional[float]
    signed_document_ref: Optional[str]
    status: str
    resubmit_count: int
    received_at: Optional[str]
    verified_at: Optional[str]
    rejected_at: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DefectTicket(TypedDict):
    id: str
    project_id: str
    responsible_subcontractor_id: Optional[str]
    source_schedule_task_id: Optional[str]
    phase: str
    room: str
    description: str
    severity: str
    category: str
    reported_at: str
    coverage_anchor: str
    coverage_end_at: Optional[str]
    coverage_result: str
    status: str
    rework_count: int
    response_due_at: Optional[str]
    completion_note: Optional[str]
    assigned_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PhotoDocument(TypedDict):
    id: str
    project_id: str
    captured_at: str
    caption: str
    visibility: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
