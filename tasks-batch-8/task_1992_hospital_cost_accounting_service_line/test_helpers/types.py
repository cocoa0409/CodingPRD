"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class ServiceLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CostCenterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PhysicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CostModelStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class CostModelRefreshStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"
    LOCKED = "LOCKED"


class PayerContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class BudgetPeriodStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class CostType(str, Enum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    OVERHEAD = "OVERHEAD"


class CostBehavior(str, Enum):
    FIXED = "FIXED"
    VARIABLE = "VARIABLE"


class CapacityMeasure(str, Enum):
    MINUTES = "MINUTES"
    RVU = "RVU"
    NONE = "NONE"


class AllocationBasis(str, Enum):
    TDABC = "TDABC"
    RVU = "RVU"


class PayerType(str, Enum):
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    COMMERCIAL = "COMMERCIAL"
    SELF_PAY = "SELF_PAY"


class VarianceDirection(str, Enum):
    FAVORABLE = "FAVORABLE"
    UNFAVORABLE = "UNFAVORABLE"
    ON_BUDGET = "ON_BUDGET"


class UserRole(str, Enum):
    COST_ANALYST = "CostAnalyst"
    FINANCE_CONTROLLER = "FinanceController"
    SERVICE_LINE_MANAGER = "ServiceLineManager"


class ServiceLine(TypedDict, total=False):
    id: str
    name: str
    code: str
    base_direct_cost: float
    budgeted_volume: int
    total_direct_cost: float
    total_revenue: float
    contribution_margin: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CostCenter(TypedDict, total=False):
    id: str
    name: str
    code: str
    cost_type: str
    cost_behavior: str
    allocated_cost: float
    practical_capacity_minutes: int
    total_rvu: float
    capacity_measure: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict, total=False):
    id: str
    npi: str
    full_name: str
    specialty: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Drg(TypedDict, total=False):
    id: str
    drg_code: str
    description: str
    target_cost: float
    base_rate: float
    created_at: str
    updated_at: str
    version: int


class CostModel(TypedDict, total=False):
    id: str
    name: str
    service_line_id: str
    allocation_basis: str
    rate_factor: float
    overhead_cost_center_id: str
    status: str
    supersedes_model_id: Optional[str]
    effective_period: str
    created_at: str
    updated_at: str
    version: int


class CostModelRefresh(TypedDict, total=False):
    id: str
    model_id: str
    period: str
    proposed_rates: List[Dict[str, Any]]
    data_quality_score: float
    status: str
    variance_report: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    service_line_id: str
    physician_id: str
    drg_id: str
    cost_model_id: str
    period: str
    expected_reimbursement: float
    status: str
    total_direct_cost: float
    total_indirect_allocated: float
    total_cost: float
    margin: float
    version_at_post: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger line (PRD §2.4): id + created_at only — no updated_at, no version.
class ActivityCostLine(TypedDict, total=False):
    id: str
    case_id: str
    cost_center_id: str
    quantity: float
    is_overhead_line: bool
    allocated_amount: float
    created_at: str


class Implant(TypedDict, total=False):
    id: str
    case_id: str
    item_code: str
    vendor: str
    unit_cost: float
    quantity: int
    created_at: str
    updated_at: str
    version: int


# Append-only ledger line (PRD §2.4): id + created_at only — no updated_at, no version.
class SupplyLine(TypedDict, total=False):
    id: str
    case_id: str
    supply_code: str
    unit_cost: float
    quantity: int
    created_at: str


class PayerContract(TypedDict, total=False):
    id: str
    service_line_id: str
    payer_name: str
    payer_type: str
    contracted_rate: float
    effective_period: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetPeriod(TypedDict, total=False):
    id: str
    cost_center_id: str
    period: str
    static_budget_amount: float
    status: str
    actual_indirect_volume: float
    flexed_overhead: float
    variance_amount: float
    variance_direction: str
    constraints_note: str
    created_at: str
    updated_at: str
    version: int
