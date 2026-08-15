"""Domain types: entity TypedDicts, status enums, role enum for the Legal Ops API."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    MANAGER = "LegalOpsManager"
    ANALYST = "LegalOpsAnalyst"
    EXECUTIVE = "LegalOpsExecutive"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class FiscalPeriodStatus(str, Enum):
    OPEN = "OPEN"
    SOFT_CLOSED = "SOFT_CLOSED"
    HARD_CLOSED = "HARD_CLOSED"
    REOPENED = "REOPENED"


class PracticeAreaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class FirmStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class FirmTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class MatterStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    ARCHIVED = "ARCHIVED"


class CounselStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class BudgetPosture(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EXCEEDED = "EXCEEDED"


class AccrualStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    MATCHED = "MATCHED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class InvoicePaymentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class AccrualMatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"
    FULLY_MATCHED = "FULLY_MATCHED"
    OVER_BILLED = "OVER_BILLED"


class SpendLineSourceStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class DashboardStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class CostModelDecision(str, Enum):
    INSOURCE_CHEAPER = "INSOURCE_CHEAPER"
    OUTSOURCE_CHEAPER = "OUTSOURCE_CHEAPER"
    BREAK_EVEN = "BREAK_EVEN"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# All primary resources carry id / created_at / updated_at / version.
# SpendLine is the single append-only exception: only id + created_at.
# ---------------------------------------------------------------------------

class LegalDepartment(TypedDict, total=False):
    id: str
    name: str
    budget_warning_pct: float
    budget_critical_pct: float
    deflection_target_pct: float
    active_fiscal_period_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FiscalPeriod(TypedDict, total=False):
    id: str
    label: str
    start_date: str
    end_date: str
    status: str
    reopen_count: int
    total_actual_spend_cents: int
    total_accrual_cents: int
    created_at: str
    updated_at: str
    version: int


class PracticeArea(TypedDict, total=False):
    id: str
    code: str
    display_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MatterType(TypedDict, total=False):
    id: str
    practice_area_id: str
    code: str
    display_name: str
    default_budget_cents: int
    created_at: str
    updated_at: str
    version: int


class OutsideCounselFirm(TypedDict, total=False):
    id: str
    name: str
    tier: str
    blended_hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Matter(TypedDict, total=False):
    id: str
    matter_number: str
    title: str
    practice_area_id: str
    matter_type_id: str
    fiscal_period_id: str
    primary_firm_id: Optional[str]
    lead_counsel_id: str
    status: str
    budget_cents: int
    actual_spend_cents: int
    accrual_outstanding_cents: int
    cycle_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InHouseCounsel(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    annual_capacity_hours: int
    loaded_hourly_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MatterAssignment(TypedDict, total=False):
    id: str
    matter_id: str
    counsel_id: str
    allocated_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Budget(TypedDict, total=False):
    id: str
    fiscal_period_id: str
    practice_area_id: str
    matter_type_id: Optional[str]
    allocated_cents: int
    consumed_cents: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Accrual(TypedDict, total=False):
    id: str
    matter_id: str
    fiscal_period_id: str
    firm_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    matter_id: str
    firm_id: str
    fiscal_period_id: str
    invoice_number: str
    amount_cents: int
    payment_status: str
    accrual_match_status: str
    matched_accrual_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpendLine(TypedDict, total=False):
    # Append-only ledger row: carries ONLY id + created_at (no updated_at, no version)
    id: str
    created_at: str
    matter_id: str
    fiscal_period_id: str
    firm_id: str
    invoice_id: str
    posting_date: str
    amount_cents: int
    source_status: str
    reversal_of_id: Optional[str]


class Dashboard(TypedDict, total=False):
    id: str
    fiscal_period_id: str
    snapshot_label: str
    total_matters_opened: int
    total_matters_closed: int
    mean_cycle_days: Optional[float]
    total_actual_spend_cents: int
    total_accrual_outstanding_cents: int
    budget_accuracy_pct: Optional[float]
    deflection_rate_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int
