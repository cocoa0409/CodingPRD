"""Domain types for the Contract Lifecycle Management API.

Entity TypedDicts, status enums, and the role enum, derived from the PRD's
resource model. Resources carrying the standard system-managed field set
(id, created_at, updated_at, version) are distinguished from the two
write-once records (ApprovalStep, AuditEvent) that carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLAUSE_LIBRARIAN = "ClauseLibrarian"
    CONTRACT_MANAGER = "ContractManager"
    CONTRACT_APPROVER = "ContractApprover"
    RISK_OFFICER = "RiskOfficer"
    SIGNER = "Signer"


# ─── Status enums ─────────────────────────────────────────────────────

class ClauseTemplateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ContractTemplateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REDLINING = "REDLINING"
    APPROVED = "APPROVED"
    OUT_FOR_SIGNATURE = "OUT_FOR_SIGNATURE"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    CANCELLED = "CANCELLED"


class ContractVersionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SUPERSEDED = "SUPERSEDED"
    ACCEPTED = "ACCEPTED"


class ApprovalWorkflowStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class SignatureRequestStatus(str, Enum):
    SENT = "SENT"
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class ObligationStatus(str, Enum):
    OPEN = "OPEN"
    FULFILLED = "FULFILLED"
    BREACHED = "BREACHED"
    WAIVED = "WAIVED"


class DeviationApprovalStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class DeviationDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class RenewalAlertStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class RenewalResolution(str, Enum):
    RENEWED = "RENEWED"
    LET_LAPSE = "LET_LAPSE"


class Party(str, Enum):
    INTERNAL = "INTERNAL"
    COUNTERPARTY = "COUNTERPARTY"


class ClauseCategory(str, Enum):
    LIABILITY = "LIABILITY"
    INDEMNITY = "INDEMNITY"
    TERMINATION = "TERMINATION"
    PAYMENT = "PAYMENT"
    CONFIDENTIALITY = "CONFIDENTIALITY"
    OTHER = "OTHER"


class AuditEventType(str, Enum):
    CONTRACT_CREATED = "CONTRACT_CREATED"
    VERSION_CREATED = "VERSION_CREATED"
    SUBMITTED = "SUBMITTED"
    REDLINE_OPENED = "REDLINE_OPENED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENT_FOR_SIGNATURE = "SENT_FOR_SIGNATURE"
    SIGNED = "SIGNED"
    ACTIVATED = "ACTIVATED"
    RENEWED = "RENEWED"
    TERMINATED = "TERMINATED"
    OBLIGATION_BREACHED = "OBLIGATION_BREACHED"
    DEVIATION_GRANTED = "DEVIATION_GRANTED"
    DEVIATION_DENIED = "DEVIATION_DENIED"


# ─── Entity TypedDicts ────────────────────────────────────────────────
# Entities below carry the standard system fields: id, created_at,
# updated_at, version.

class Organization(TypedDict):
    id: str
    name: str
    risk_appetite_threshold: int
    auto_renew_lead_days: int
    created_at: str
    updated_at: str
    version: int


class ClauseTemplate(TypedDict):
    id: str
    organization_id: str
    clause_key: str
    category: str
    standard_text: str
    risk_weight: int
    is_mandatory: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractTemplate(TypedDict):
    id: str
    organization_id: str
    name: str
    clause_template_ids: List[str]
    default_term_months: int
    auto_renew_default: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    organization_id: str
    contract_template_id: str
    counterparty_name: str
    title: str
    term_months: int
    auto_renew: bool
    effective_date: Optional[str]
    expiry_date: Optional[str]
    current_version_id: Optional[str]
    drafter_user_id: str
    risk_score: int
    renewal_cycle_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractVersion(TypedDict):
    id: str
    contract_id: str
    version_number: int
    authored_by_party: str
    authored_by_user_id: Optional[str]
    clauses: List[Any]
    deviation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ApprovalWorkflow(TypedDict):
    id: str
    contract_id: str
    pinned_version_id: str
    required_approver_count: int
    approvals_received: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SignatureRequest(TypedDict):
    id: str
    contract_id: str
    signer_party: str
    signer_name: str
    signed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Obligation(TypedDict):
    id: str
    contract_id: str
    description: str
    owner_party: str
    due_date: str
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeviationApproval(TypedDict):
    id: str
    contract_id: str
    contract_version_id: str
    clause_template_id: str
    justification: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalAlert(TypedDict):
    id: str
    contract_id: str
    trigger_date: str
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Write-once records: id + created_at only (PRD §2.4). No updated_at, no version.

class ApprovalStep(TypedDict):
    id: str
    approval_workflow_id: str
    approver_user_id: str
    decision: str
    comment: Optional[str]
    created_at: str


class AuditEvent(TypedDict):
    id: str
    contract_id: str
    event_type: str
    actor_user_id: Optional[str]
    detail: Optional[str]
    created_at: str
