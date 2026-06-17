"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    HRBP = "HRBP"
    FINANCE_CONTROLLER = "FinanceController"
    COMPENSATION_ANALYST = "CompensationAnalyst"
    HR_DIRECTOR = "HRDirector"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class EmployeeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"


class PositionLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    REQUISITIONED = "REQUISITIONED"
    FUNDED = "FUNDED"
    FROZEN = "FROZEN"
    ABOLISHED = "ABOLISHED"


class PositionOccupancyStatus(str, Enum):
    VACANT = "VACANT"
    FILLED = "FILLED"


class CostCenterPosture(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class IncumbentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VACATED = "VACATED"


class FreezeOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class RequisitionType(str, Enum):
    NEW_HIRE = "NEW_HIRE"
    BACKFILL = "BACKFILL"


class RequisitionStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReclassDirection(str, Enum):
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"
    LATERAL = "LATERAL"


class ReclassStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ForecastPeriodStatus(str, Enum):
    DRAFT = "DRAFT"
    SNAPSHOTTED = "SNAPSHOTTED"


class BudgetAdjustmentStatus(str, Enum):
    APPLIED = "APPLIED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true — id + created_at + updated_at + version
class Employee(TypedDict):
    id: str
    full_name: str
    email: str
    annual_salary_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only config: ONLY id + created_at
class Grade(TypedDict):
    id: str
    code: str
    band_min_cents: int
    band_mid_cents: int
    band_max_cents: int
    rank: int
    created_at: str


# common_fields: true
class CostCenter(TypedDict):
    id: str
    name: str
    code: str
    annual_budget_cents: int
    adjusted_budget_cents: int
    fte_cap: float
    committed_fte: float
    committed_cost_cents: int
    filled_fte: float
    available_budget_cents: int
    posture: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Position(TypedDict):
    id: str
    cost_center_id: str
    grade_id: str
    manager_position_id: Optional[str]
    title: str
    fte: float
    lifecycle_status: str
    occupancy_status: str
    span_of_control: int
    planned_cost_cents: int
    actual_cost_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Incumbent(TypedDict):
    id: str
    position_id: str
    employee_id: str
    start_date: str
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class FreezeOrder(TypedDict):
    id: str
    cost_center_id: str
    effective_from: str
    effective_to: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Requisition(TypedDict):
    id: str
    position_id: str
    req_type: str
    justification: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class ReclassRequest(TypedDict):
    id: str
    position_id: str
    target_grade_id: str
    from_grade_rank: int
    target_grade_rank: int
    direction: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class ForecastPeriod(TypedDict):
    id: str
    cost_center_id: str
    fiscal_label: str
    planned_fte: float
    actual_fte: Optional[float]
    variance_fte: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only budget event: ONLY id + created_at
class BudgetAdjustment(TypedDict):
    id: str
    cost_center_id: str
    amount_cents: int
    memo: str
    status: str
    created_at: str
