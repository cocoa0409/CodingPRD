"""Domain types: entity TypedDicts, status enums, and the role enum.

Mirrors the entities and lifecycle states described in the Grant Management PRD
(§2.4 common properties, §3 workflows). Append-only ledger artifacts carry only
id + created_at (no updated_at, no version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Status enums (PRD §3 lifecycle states)
# --------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISIONS_REQUESTED = "REVISIONS_REQUESTED"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PENDING_CLOSEOUT = "PENDING_CLOSEOUT"
    CLOSED = "CLOSED"


class RateType(str, Enum):
    NEGOTIATED = "NEGOTIATED"
    DE_MINIMIS = "DE_MINIMIS"


class BaseType(str, Enum):
    MTDC = "MTDC"
    TDC = "TDC"


class RateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class SubawardStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FundCategory(str, Enum):
    PERSONNEL = "PERSONNEL"
    EQUIPMENT = "EQUIPMENT"
    TRAVEL = "TRAVEL"
    SUPPLIES = "SUPPLIES"
    SUBAWARD_PASS_THROUGH = "SUBAWARD_PASS_THROUGH"
    INDIRECT = "INDIRECT"


class DrawdownStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISBURSED = "DISBURSED"
    RETURNED = "RETURNED"


class ReportBasis(str, Enum):
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class FinancialReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ProgressReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class SingleAuditStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    RESOLVED = "RESOLVED"


class FindingSeverity(str, Enum):
    DEFICIENCY = "DEFICIENCY"
    SIGNIFICANT_DEFICIENCY = "SIGNIFICANT_DEFICIENCY"
    MATERIAL_WEAKNESS = "MATERIAL_WEAKNESS"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class UserRole(str, Enum):
    GRANT_WRITER = "GrantWriter"
    FINANCE_OFFICER = "FinanceOfficer"
    PROGRAM_MANAGER = "ProgramManager"
    AGENCY_OFFICER = "AgencyOfficer"
    AUDITOR = "Auditor"
    ANONYMOUS = "Anonymous"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
class NofoApplication(TypedDict, total=False):
    id: str
    nofo_number: str
    applicant_org_name: str
    requested_amount_cents: int
    federal_share_pct: float
    period_start_date: str
    period_end_date: str
    supersedes_application_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    application_id: str
    total_award_cents: int
    federal_share_pct: float
    federal_ceiling_cents: int
    period_start_date: str
    period_end_date: str
    federal_drawn_cents: int
    federal_approved_expenditures_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IndirectCostRate(TypedDict, total=False):
    id: str
    award_id: str
    rate_type: str
    negotiated_rate: Optional[float]
    base_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Subaward(TypedDict, total=False):
    id: str
    award_id: str
    subrecipient_name: str
    subaward_amount_cents: int
    risk_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RestrictedFund(TypedDict, total=False):
    id: str
    award_id: str
    category: str
    budgeted_cents: int
    allocated_cents: int
    priority_order: int
    created_at: str
    updated_at: str
    version: int


class Drawdown(TypedDict, total=False):
    id: str
    award_id: str
    initiated_by_user_id: str
    amount_cents: int
    allocation_plan: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger artifact — PRD §2.4: carries only id + created_at.
class FundAllocation(TypedDict, total=False):
    id: str
    drawdown_id: str
    restricted_fund_id: str
    amount_cents: int
    created_at: str


class FinancialReport(TypedDict, total=False):
    id: str
    award_id: str
    period_label: str
    report_basis: str
    direct_cost_lines: List[dict]
    disallowed_cents: int
    approved_direct_cents: int
    indirect_cost_cents: int
    reimbursable_cents: int
    certified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgressReport(TypedDict, total=False):
    id: str
    award_id: str
    period_label: str
    milestones_met: int
    milestones_planned: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SingleAudit(TypedDict, total=False):
    id: str
    award_id: str
    fiscal_year: int
    federal_expenditures_cents: int
    audit_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    single_audit_id: str
    severity: str
    questioned_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
