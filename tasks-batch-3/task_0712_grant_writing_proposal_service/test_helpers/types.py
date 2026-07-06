"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this service carries the full common-field set (id, created_at,
updated_at, version), per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    GRANT_WRITER = "GrantWriter"
    CLIENT_CONTACT = "ClientContact"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    OPS = "Ops"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class OpportunityStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class FeeModel(str, Enum):
    SUCCESS_FEE = "SUCCESS_FEE"
    HOURLY = "HOURLY"
    RETAINER = "RETAINER"


class MatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PURSUING = "PURSUING"
    DECLINED = "DECLINED"


class ProposalStatus(str, Enum):
    DRAFTING = "DRAFTING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"


class BudgetCategory(str, Enum):
    PERSONNEL = "PERSONNEL"
    EQUIPMENT = "EQUIPMENT"
    TRAVEL = "TRAVEL"
    INDIRECT = "INDIRECT"
    OTHER = "OTHER"


class DeliverableKind(str, Enum):
    NARRATIVE = "NARRATIVE"
    BUDGET_JUSTIFICATION = "BUDGET_JUSTIFICATION"
    ATTACHMENT = "ATTACHMENT"


class ContentStatus(str, Enum):
    OUTLINE = "OUTLINE"
    DRAFTED = "DRAFTED"
    FINAL = "FINAL"


class ApprovalStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"


class RevisionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"


class SubmissionStatus(str, Enum):
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class TimeEntryStatus(str, Enum):
    LOGGED = "LOGGED"
    BILLED = "BILLED"


class InvoiceKind(str, Enum):
    SUCCESS_FEE = "SUCCESS_FEE"
    HOURLY = "HOURLY"
    RETAINER = "RETAINER"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    VOID = "VOID"


class AwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED_OUT = "CLOSED_OUT"


class ComplianceStatus(str, Enum):
    GREEN = "GREEN"
    AT_RISK = "AT_RISK"
    DELINQUENT = "DELINQUENT"


class ReportType(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUPPLEMENTAL = "SUPPLEMENTAL"


class ReportStatus(str, Enum):
    PENDING = "PENDING"
    FILED = "FILED"
    LATE = "LATE"


class SnippetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


# --------------------------------------------------------------------------
# Entity TypedDicts — all carry the full common-field set (id, created_at,
# updated_at, version) per PRD §2.4.
# --------------------------------------------------------------------------
class Client(TypedDict):
    id: str
    org_name: str
    ein: str
    mission_areas: List[str]
    annual_budget_cents: int
    contact_email: str
    status: str
    proposals_submitted_count: int
    proposals_won_count: int
    win_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class FundingOpportunity(TypedDict):
    id: str
    funder_name: str
    title: str
    focus_areas: List[str]
    ceiling_amount_cents: int
    floor_amount_cents: int
    portal_name: str
    deadline_utc: str
    min_org_budget_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    client_id: str
    fee_model: str
    success_fee_pct: float
    hourly_rate_cents: int
    retainer_monthly_cents: int
    retainer_included_hours: int
    overage_rate_cents: int
    status: str
    ytd_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class MatchAssessment(TypedDict):
    id: str
    client_id: str
    opportunity_id: str
    score: int
    eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict):
    id: str
    engagement_id: str
    match_id: str
    requested_amount_cents: int
    revision_round: int
    budget_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetLine(TypedDict):
    id: str
    proposal_id: str
    category: str
    label: str
    amount_cents: int
    indirect_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    proposal_id: str
    kind: str
    title: str
    body: str
    content_status: str
    approval_status: str
    open_revision_count: int
    created_at: str
    updated_at: str
    version: int


class RevisionRequest(TypedDict):
    id: str
    deliverable_id: str
    supersedes_revision_id: Optional[str]
    note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    proposal_id: str
    portal_name: str
    submitted_at_utc: str
    decision_due_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    id: str
    engagement_id: str
    proposal_id: Optional[str]
    minutes: int
    period_yyyymm: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    engagement_id: str
    kind: str
    period_start_yyyymm: Optional[str]
    period_end_yyyymm: Optional[str]
    award_id: Optional[str]
    line_count: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict):
    id: str
    submission_id: str
    awarded_amount_cents: int
    period_of_performance_months: int
    report_cadence_months: int
    compliance_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict):
    id: str
    award_id: str
    due_utc: str
    covers_window_start_utc: Optional[str]
    report_type: str
    sequence_index: int
    submitted_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BoilerplateSnippet(TypedDict):
    id: str
    client_id: str
    section_key: str
    body: str
    usage_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
