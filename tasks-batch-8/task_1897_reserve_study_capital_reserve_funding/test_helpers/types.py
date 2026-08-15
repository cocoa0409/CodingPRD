"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RESERVE_SPECIALIST = "ReserveSpecialist"
    BOARD_MEMBER = "BoardMember"
    ASSOCIATION_MANAGER = "AssociationManager"


class ComplianceStatus(str, Enum):
    COMPLIANCE_UNKNOWN = "COMPLIANCE_UNKNOWN"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class StudyType(str, Enum):
    FULL = "FULL"
    UPDATE_WITH_VISIT = "UPDATE_WITH_VISIT"
    UPDATE_NO_VISIT = "UPDATE_NO_VISIT"


class ComponentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ComponentCategory(str, Enum):
    ROOFING = "ROOFING"
    PAVING = "PAVING"
    MECHANICAL = "MECHANICAL"
    EXTERIOR = "EXTERIOR"
    INTERIOR = "INTERIOR"
    RECREATION = "RECREATION"
    OTHER = "OTHER"


class PlanType(str, Enum):
    BASELINE = "BASELINE"
    THRESHOLD = "THRESHOLD"
    FULL = "FULL"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    RECOMMENDED = "RECOMMENDED"
    SELECTED = "SELECTED"
    RETIRED = "RETIRED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class ApprovalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class ReconciliationStatus(str, Enum):
    UNRECONCILED = "UNRECONCILED"
    MATCHED = "MATCHED"
    VARIANCE_ACCEPTED = "VARIANCE_ACCEPTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ExpenditureKind(str, Enum):
    PLANNED_REPLACEMENT = "PLANNED_REPLACEMENT"
    UNPLANNED_REPAIR = "UNPLANNED_REPAIR"


class DisclosureType(str, Enum):
    ADOPTION_SUMMARY = "ADOPTION_SUMMARY"
    ANNUAL_STATEMENT = "ANNUAL_STATEMENT"


class DisclosureStatus(str, Enum):
    PENDING = "PENDING"
    DISTRIBUTED = "DISTRIBUTED"
    VOIDED = "VOIDED"


class RiskVerdict(str, Enum):
    AT_RISK = "AT_RISK"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries id / created_at / updated_at /
# version per PRD §2.7.
# ---------------------------------------------------------------------------

class StateReserveRule(TypedDict):
    id: str
    state_code: str
    min_percent_funded_pct: float
    allowed_plan_types: List[str]
    site_visit_interval_years: int
    disclosure_deadline_days: int
    annual_update_required: bool
    created_at: str
    updated_at: str
    version: int


class Association(TypedDict):
    id: str
    name: str
    state_code: str
    fiscal_year_end_month: int
    reserve_cash_balance_cents: int
    current_annual_contribution_cents: int
    last_annual_update_fiscal_year: Optional[int]
    statutory_compliance_status: str
    next_site_visit_due_date: Optional[str]
    annual_update_overdue: bool
    created_at: str
    updated_at: str
    version: int


class ReserveStudy(TypedDict):
    id: str
    association_id: str
    fiscal_year: int
    study_type: str
    inflation_rate: float
    interest_rate: float
    status: str
    window_start_date: str
    window_end_date_exclusive: str
    fully_funded_balance_cents: int
    percent_funded: float
    adopted_at: Optional[str]
    adopted_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict):
    id: str
    study_id: str
    name: str
    category: str
    useful_life_years: int
    remaining_useful_life_years: int
    current_replacement_cost_cents: int
    is_included_in_funding: bool
    status: str
    actual_expenditure_cents: int
    last_replaced_fiscal_year: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FundingPlan(TypedDict):
    id: str
    study_id: str
    plan_type: str
    status: str
    starting_cash_cents: int
    annual_contribution_cents: int
    threshold_floor_cents: Optional[int]
    computed_at: str
    created_at: str
    updated_at: str
    version: int


class SiteVisit(TypedDict):
    id: str
    association_id: str
    visit_date: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Expenditure(TypedDict):
    id: str
    association_id: str
    component_id: str
    amount_cents: int
    incurred_date: str
    kind: str
    fiscal_year: int
    approval_status: str
    reconciliation_status: str
    planned_chronological_cents: Optional[int]
    variance_chronological_cents: Optional[int]
    planned_forward_cents: Optional[int]
    variance_forward_cents: Optional[int]
    component_rul_before_years: Optional[int]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disclosure(TypedDict):
    id: str
    study_id: str
    disclosure_type: str
    status: str
    due_date: str
    distributed_at: Optional[str]
    is_late: bool
    allocation_lines: List[dict]
    created_at: str
    updated_at: str
    version: int
