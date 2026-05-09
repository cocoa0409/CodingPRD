"""Domain types for the Research Funding API: entity TypedDicts, status enums, role enum.

Reflects PRD §2.1 (roles), §2.4 (common resource properties), §2.11 (enumerations),
and the per-entity status sets that appear in §3.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# --- Roles (PRD §2.1) ---

class UserRole(str, Enum):
    PRINCIPAL_INVESTIGATOR = "PrincipalInvestigator"
    DEPARTMENT_APPROVER = "DepartmentApprover"
    FINANCE_OFFICER = "FinanceOfficer"
    RESEARCH_ADMIN = "ResearchAdmin"
    AUDIT_OFFICER = "AuditOfficer"
    PEER_REVIEWER = "PeerReviewer"
    TEST_DRIVER = "TestDriver"


# --- Funding source (PRD §2.11) ---

class FundingSource(str, Enum):
    NATIONAL = "NATIONAL"
    PROVINCIAL = "PROVINCIAL"
    ENTERPRISE = "ENTERPRISE"
    INTERNAL = "INTERNAL"


# --- Budget category (PRD §2.11) ---

class BudgetCategory(str, Enum):
    PERSONNEL = "PERSONNEL"
    EQUIPMENT = "EQUIPMENT"
    MATERIALS = "MATERIALS"
    TRAVEL = "TRAVEL"
    CONFERENCE = "CONFERENCE"
    OUTSOURCING = "OUTSOURCING"


# --- Recommendation (PRD §2.11) ---

class PeerReviewRecommendation(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REVISE = "REVISE"


# --- Residual fund action (PRD §2.11) ---

class ResidualFundAction(str, Enum):
    RETURN = "RETURN"
    REALLOCATE = "REALLOCATE"
    CARRYOVER = "CARRYOVER"


# --- Allocation base (PRD §2.11) ---

class AllocationBase(str, Enum):
    DIRECT_COST = "DIRECT_COST"
    PERSONNEL_COST = "PERSONNEL_COST"
    FLOOR_AREA = "FLOOR_AREA"


# --- Compliance rule severity (PRD §2.11) ---

class ComplianceSeverity(str, Enum):
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"
    WARN = "WARN"


# --- Audit finding severity (PRD §2.11) ---

class AuditFindingSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# --- Per-entity status enums (PRD §3) ---

class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class BudgetItemStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class BudgetAdjustmentStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReimbursementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class ClosingAuditStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECTIFICATION_REQUIRED = "RECTIFICATION_REQUIRED"
    CLOSED = "CLOSED"


class DecisionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AuditLogSubjectType(str, Enum):
    BUDGET_ITEM = "BUDGET_ITEM"
    BUDGET_ADJUSTMENT = "BUDGET_ADJUSTMENT"
    REIMBURSEMENT = "REIMBURSEMENT"


class AuditLogAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REWORK = "REWORK"
    PAY = "PAY"
    LOCK = "LOCK"
    ADJUST = "ADJUST"


# --- Entity TypedDicts ---
# common_fields=true entities carry id + created_at + updated_at + version.
# common_fields=false entities (PeerReview, IndirectCostAllocation, AuditLog) carry only id + created_at.

class Project(TypedDict, total=False):
    id: str
    title: str
    principal_investigator_id: str
    department_id: str
    funding_source: str
    proposal_text: str
    requested_amount: float
    project_code: Optional[str]
    planned_start_date: int
    planned_end_date: int
    total_budget: float
    total_reimbursed: float
    indirect_cost_amount: Optional[float]
    status: str
    closing_findings_count: int
    created_at: str
    updated_at: str
    version: int


class PeerReview(TypedDict, total=False):
    """Append-only — only id + created_at as common fields."""
    id: str
    project_id: str
    reviewer_id: str
    score: int
    recommendation: str
    comments: str
    created_at: str


class BudgetItem(TypedDict, total=False):
    id: str
    project_id: str
    category: str
    requested_amount: float
    approved_amount: Optional[float]
    spent_amount: float
    remaining_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetAdjustment(TypedDict, total=False):
    id: str
    project_id: str
    line_changes: List[Dict[str, Any]]
    justification: str
    pi_decision: str
    dept_decision: str
    finance_decision: str
    pinned_budget_versions: Dict[str, int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reimbursement(TypedDict, total=False):
    id: str
    project_id: str
    budget_item_id: str
    expense_category: str
    amount: float
    invoice_number: str
    invoice_date: int
    invoice_authenticated: bool
    attachments: List[Dict[str, Any]]
    vendor_id: str
    pi_decision: str
    dept_decision: str
    finance_decision: str
    rejection_reason: Optional[str]
    rework_count: int
    compliance_findings: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosingAudit(TypedDict, total=False):
    id: str
    project_id: str
    deliverables: List[Dict[str, Any]]
    residual_fund_action: str
    audit_findings: List[Dict[str, Any]]
    budget_execution_rate: float
    forward_execution_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class IndirectCostAllocation(TypedDict, total=False):
    """Append-only allocation snapshot — only id + created_at as common fields."""
    id: str
    allocation_run_id: str
    project_id: str
    allocation_base: str
    allocation_rate: float
    base_value: float
    shared_share: float
    allocated_amount: float
    created_at: str


class ComplianceRule(TypedDict, total=False):
    id: str
    rule_code: str
    applies_to_funding_source: str
    applies_to_category: str
    parameters: Dict[str, Any]
    severity: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class AuditLog(TypedDict, total=False):
    """Append-only — only id + created_at as common fields, plus occurred_at."""
    id: str
    subject_type: str
    subject_id: str
    action: str
    actor_role: str
    actor_id: str
    before_snapshot: Dict[str, Any]
    after_snapshot: Dict[str, Any]
    occurred_at: str
    created_at: str
