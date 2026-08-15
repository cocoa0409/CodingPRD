"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum — header spellings (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    CONTRACT_ANALYST = "ContractAnalyst"
    BUSINESS_OWNER = "BusinessOwner"
    LEGAL_COUNSEL = "LegalCounsel"
    FINANCE_CONTROLLER = "FinanceController"
    CHIEF_COUNSEL = "ChiefCounsel"
    SIGNATORY = "Signatory"
    OPS_ADMIN = "OpsAdmin"


class UserPrimaryRole(str, Enum):
    """Persisted primary_role spellings on the User record (PRD §2.1)."""
    CONTRACT_ANALYST = "CONTRACT_ANALYST"
    BUSINESS_OWNER = "BUSINESS_OWNER"
    LEGAL_COUNSEL = "LEGAL_COUNSEL"
    FINANCE_CONTROLLER = "FINANCE_CONTROLLER"
    CHIEF_COUNSEL = "CHIEF_COUNSEL"
    SIGNATORY = "SIGNATORY"
    OPS_ADMIN = "OPS_ADMIN"


# Header role name for a persisted primary_role (one-to-one, PRD §2.1).
PRIMARY_ROLE_TO_HEADER = {
    "CONTRACT_ANALYST": "ContractAnalyst",
    "BUSINESS_OWNER": "BusinessOwner",
    "LEGAL_COUNSEL": "LegalCounsel",
    "FINANCE_CONTROLLER": "FinanceController",
    "CHIEF_COUNSEL": "ChiefCounsel",
    "SIGNATORY": "Signatory",
    "OPS_ADMIN": "OpsAdmin",
}


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class PlaybookStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class ClauseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ClauseCategory(str, Enum):
    RISK = "RISK"
    COMMERCIAL = "COMMERCIAL"
    OPERATIONAL = "OPERATIONAL"
    REGULATORY = "REGULATORY"


class SeverityCap(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ApproverRole(str, Enum):
    LEGAL_COUNSEL = "LEGAL_COUNSEL"
    FINANCE_CONTROLLER = "FINANCE_CONTROLLER"
    BUSINESS_OWNER = "BUSINESS_OWNER"
    CHIEF_COUNSEL = "CHIEF_COUNSEL"


class ContractTypeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RiskTier(str, Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH_RISK = "HIGH_RISK"
    SANCTIONED = "SANCTIONED"


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class IntakeStatus(str, Enum):
    PENDING_TRIAGE = "PENDING_TRIAGE"
    ROUTED = "ROUTED"
    NEGOTIATION_OPENED = "NEGOTIATION_OPENED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class RoutingBucket(str, Enum):
    SELF_SERVE = "SELF_SERVE"
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    EXECUTIVE = "EXECUTIVE"


class ValueTier(str, Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class DecidedBy(str, Enum):
    SYSTEM = "SYSTEM"
    ANALYST_OVERRIDE = "ANALYST_OVERRIDE"


class DraftStatus(str, Enum):
    OPEN = "OPEN"
    REDLINING = "REDLINING"
    AWAITING_COUNTERSIGN = "AWAITING_COUNTERSIGN"
    EXECUTED = "EXECUTED"
    ABORTED = "ABORTED"


class ApprovalStatus(str, Enum):
    NO_DEVIATIONS = "NO_DEVIATIONS"
    DEVIATIONS_PENDING = "DEVIATIONS_PENDING"
    APPROVED_WITH_DEVIATIONS = "APPROVED_WITH_DEVIATIONS"
    BLOCKED = "BLOCKED"


class SignatureStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ROUTING = "ROUTING"
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED"
    FULLY_SIGNED = "FULLY_SIGNED"
    EXECUTION_RECORDED = "EXECUTION_RECORDED"


class RoundStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class DeviationStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class DeviationSeverity(str, Enum):
    STANDARD = "STANDARD"
    FALLBACK = "FALLBACK"
    NON_STANDARD = "NON_STANDARD"


class DecisionKind(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"
    ABSTAIN = "ABSTAIN"


class PacketStatus(str, Enum):
    ROUTING = "ROUTING"
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED"
    FULLY_SIGNED = "FULLY_SIGNED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"
    EXECUTION_RECORDED = "EXECUTION_RECORDED"


class ExtractionSource(str, Enum):
    STANDARD_TEXT = "STANDARD_TEXT"
    FALLBACK_POSITION = "FALLBACK_POSITION"
    APPROVED_DEVIATION = "APPROVED_DEVIATION"


class OwnerRole(str, Enum):
    BUSINESS_OWNER = "BUSINESS_OWNER"
    LEGAL_COUNSEL = "LEGAL_COUNSEL"
    FINANCE_CONTROLLER = "FINANCE_CONTROLLER"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Primary resources carry id/created_at/updated_at/version (PRD §2.4).
# Append-only audit records (TriageDecision, NegotiationRound, ApprovalDecision,
# Obligation) carry ONLY id + created_at (PRD §2.4).
# ---------------------------------------------------------------------------

class Playbook(TypedDict):
    id: str
    name: str
    status: str
    published_at: Optional[str]
    clause_count: int
    active_negotiation_count: int
    created_at: str
    updated_at: str
    version: int


class ClauseTemplate(TypedDict):
    id: str
    playbook_id: str
    clause_key: str
    category: str
    standard_text: str
    fallback_positions: List[str]
    approver_role_required: str
    deviation_severity_cap: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractType(TypedDict):
    id: str
    code: str
    display_name: str
    low_value_threshold_cents: int
    mid_value_threshold_cents: int
    high_value_threshold_cents: int
    auto_approve_below_cents: int
    requires_chief_counsel_above_cents: int
    default_business_owner_id: str
    default_legal_counsel_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Counterparty(TypedDict):
    id: str
    legal_name: str
    jurisdiction: str
    risk_tier: str
    active_negotiation_count: int
    last_executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class User(TypedDict):
    id: str
    email: str
    display_name: str
    primary_role: str
    can_sign_above_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IntakeRequest(TypedDict):
    id: str
    submitted_by_user_id: str
    contract_type_id: str
    counterparty_id: str
    contract_value_cents: int
    effective_date: str
    routing_bucket: Optional[str]
    assigned_owner_id: Optional[str]
    assigned_legal_id: Optional[str]
    triage_decision_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TriageDecision(TypedDict):
    # Append-only audit record: id + created_at only (no updated_at/version).
    id: str
    created_at: str
    intake_request_id: str
    decided_at: str
    routing_bucket: str
    value_tier: str
    counterparty_risk: str
    rationale: str
    decided_by: str


class Negotiation(TypedDict):
    id: str
    intake_request_id: str
    playbook_id: str
    playbook_version_at_pin: int
    contract_value_cents: int
    contract_type_id: str
    counterparty_id: str
    business_owner_id: str
    legal_counsel_id: str
    drafter_user_id: str
    draft_status: str
    approval_status: str
    signature_status: str
    current_round_index: int
    open_deviation_count: int
    blocking_deviation_count: int
    cycle_time_seconds: int
    total_rounds: int
    created_at: str
    updated_at: str
    version: int


class NegotiationRound(TypedDict):
    # Append-only audit record: id + created_at only (no updated_at/version).
    id: str
    created_at: str
    negotiation_id: str
    round_index: int
    opened_at: str
    closed_at: Optional[str]
    opened_by_user_id: str
    closed_by_user_id: Optional[str]
    status: str
    change_summary: str
    clause_change_count: int
    round_duration_seconds: Optional[int]


class Deviation(TypedDict):
    id: str
    negotiation_id: str
    round_id: str
    clause_template_id: str
    proposed_text: str
    fallback_index: int
    severity: str
    risk_score: int
    required_approver_role: str
    escalated_to_chief_counsel: bool
    assigned_approver_id: Optional[str]
    status: str
    opened_at: str
    resolved_at: Optional[str]
    cycle_time_seconds: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ApprovalDecision(TypedDict):
    # Append-only audit record: id + created_at only (no updated_at/version).
    id: str
    created_at: str
    deviation_id: str
    decided_by_user_id: str
    decision: str
    decision_rationale: Optional[str]
    decided_at: str
    snapshot_clause_version: int


class SignatoryEntry(TypedDict):
    user_id: str
    order_index: int
    authority_cap_cents: int


class SignedRecordEntry(TypedDict):
    user_id: str
    signed_at: str
    signature_hash: str


class SignaturePacket(TypedDict):
    id: str
    negotiation_id: str
    signatories: List[SignatoryEntry]
    signature_window_opens_at: str
    signature_window_closes_at: str
    signed_record: List[SignedRecordEntry]
    status: str
    created_at: str
    updated_at: str
    version: int


class Obligation(TypedDict):
    # Append-only audit record: id + created_at only (no updated_at/version).
    id: str
    created_at: str
    negotiation_id: str
    clause_template_id: str
    obligation_text: str
    extraction_source: str
    owner_role: str
    due_offset_days: int
    due_date: str
    extracted_at: str
