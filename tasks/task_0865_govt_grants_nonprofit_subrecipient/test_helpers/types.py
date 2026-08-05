"""Domain types: entity TypedDicts, status enums, role enum.

All names use the PRD's domain terminology (nonprofits, NOFOs, applications,
subawards, drawdowns, risk assessments, monitoring visits, single audits, findings).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────────────
class UserRole(str, Enum):
    PROGRAM_OFFICER = "ProgramOfficer"
    PANELIST = "Panelist"
    GRANTS_MANAGER = "GrantsManager"
    SUBRECIPIENT = "Subrecipient"


# ─── Status enums ─────────────────────────────────────────────
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SCORED = "SCORED"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"


class SubawardStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSEOUT_PENDING = "CLOSEOUT_PENDING"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class DrawdownStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    DENIED = "DENIED"
    PAID = "PAID"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    CAP_SUBMITTED = "CAP_SUBMITTED"
    CAP_ACCEPTED = "CAP_ACCEPTED"
    RESOLVED = "RESOLVED"


class MonitoringVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"


class SingleAuditStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class IntakeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class IndirectMethod(str, Enum):
    DE_MINIMIS = "DE_MINIMIS"
    NEGOTIATED = "NEGOTIATED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class BudgetCategory(str, Enum):
    PERSONNEL = "PERSONNEL"
    FRINGE = "FRINGE"
    TRAVEL = "TRAVEL"
    SUPPLIES = "SUPPLIES"
    EQUIPMENT = "EQUIPMENT"
    CONTRACTUAL = "CONTRACTUAL"
    OTHER = "OTHER"


# ─── Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ───
class Nonprofit(TypedDict):
    id: str
    legal_name: str
    uei: str
    ein: str
    cumulative_federal_expenditures_cents: int
    latest_risk_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NOFO(TypedDict):
    id: str
    title: str
    cfda_number: str
    total_pool_cents: int
    remaining_pool_cents: int
    max_award_cents: int
    indirect_cost_cap_pct: float
    open_date: str
    close_date: str
    intake_status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    nofo_id: str
    nonprofit_id: str
    project_title: str
    requested_amount_cents: int
    proposed_period_start: str
    proposed_period_end: str
    indirect_method: str
    negotiated_indirect_rate: Optional[float]
    status: str
    review_count: int
    average_score: Optional[float]
    awarded_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Subaward(TypedDict):
    id: str
    application_id: str
    nonprofit_id: str
    nofo_id: str
    period_start: str
    period_end: str
    total_budget_cents: int
    indirect_method: str
    negotiated_indirect_rate: Optional[float]
    indirect_cost_cents: int
    federal_share_cents: int
    obligated_cents: int
    disbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Drawdown(TypedDict):
    id: str
    subaward_id: str
    requested_amount_cents: int
    period_covered_start: str
    period_covered_end: str
    disallowed_amount_cents: int
    provisional_reimbursable_cents: int
    final_reimbursable_cents: Optional[int]
    reimbursable_cents: int
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict):
    id: str
    subaward_id: str
    assessed_by_user_id: str
    findings_component: int
    audit_component: int
    velocity_component: int
    size_component: int
    risk_score: int
    risk_tier: str
    created_at: str
    updated_at: str
    version: int


class MonitoringVisit(TypedDict):
    id: str
    subaward_id: str
    monitor_user_id: str
    scheduled_start: str
    scheduled_end: str
    outcome: Optional[str]
    finding_severity: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceReport(TypedDict):
    id: str
    subaward_id: str
    reporting_period_start: str
    reporting_period_end: str
    metric_target: int
    metric_actual: int
    outcome_narrative: Optional[str]
    on_track: bool
    created_at: str
    updated_at: str
    version: int


class SingleAudit(TypedDict):
    id: str
    nonprofit_id: str
    fiscal_year: int
    total_federal_expenditures_cents: int
    audit_required: bool
    material_weakness: bool
    reported_finding_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict):
    id: str
    subaward_id: str
    source_kind: str
    origin_ref_id: str
    severity: str
    description: str
    corrective_action_plan: Optional[str]
    cap_due_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only records (common_fields: false → ONLY id + created_at) ───
class PanelReview(TypedDict):
    id: str
    application_id: str
    reviewer_user_id: str
    score: int
    comments: Optional[str]
    created_at: str


class BudgetLine(TypedDict):
    id: str
    subaward_id: str
    category: str
    amount_cents: int
    federal_share_pct: float
    description: Optional[str]
    created_at: str
