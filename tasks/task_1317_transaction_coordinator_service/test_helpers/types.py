"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class CoordinatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class FileStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PENDING_CLOSE = "PENDING_CLOSE"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"
    TERMINATED = "TERMINATED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"
    OVERDUE = "OVERDUE"


class DeadlineStatus(str, Enum):
    PENDING = "PENDING"
    MET = "MET"
    WAIVED = "WAIVED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ReminderStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    CANCELLED = "CANCELLED"


class DocumentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CommunicationStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ROUTED = "ROUTED"
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED"
    FULLY_SIGNED = "FULLY_SIGNED"
    EFFECTIVE = "EFFECTIVE"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class SignatureRequestStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ContractType(str, Enum):
    PURCHASE_SALE = "PURCHASE_SALE"
    LISTING_ONLY = "LISTING_ONLY"


class BillingModel(str, Enum):
    PER_FILE = "PER_FILE"
    SUBSCRIPTION = "SUBSCRIPTION"


class DeadlineKind(str, Enum):
    INSPECTION = "INSPECTION"
    APPRAISAL = "APPRAISAL"
    FINANCING = "FINANCING"


class DayConvention(str, Enum):
    CALENDAR = "CALENDAR"
    BUSINESS = "BUSINESS"


class AuditStatus(str, Enum):
    NONE = "NONE"
    PASS = "PASS"
    FAIL = "FAIL"


class EntryKind(str, Enum):
    LOG = "LOG"
    ESCALATION = "ESCALATION"
    SYSTEM = "SYSTEM"


class Party(str, Enum):
    BUYER_AGENT = "BUYER_AGENT"
    SELLER_AGENT = "SELLER_AGENT"
    LENDER = "LENDER"
    TITLE = "TITLE"
    COORDINATOR = "COORDINATOR"
    SYSTEM = "SYSTEM"


class Direction(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    SYSTEM = "SYSTEM"


class TitleStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"


class LenderStatus(str, Enum):
    PENDING = "PENDING"
    CLEAR_TO_CLOSE = "CLEAR_TO_CLOSE"
    NOT_REQUIRED = "NOT_REQUIRED"


class OverallStatus(str, Enum):
    PENDING = "PENDING"
    CLEAR_TO_CLOSE = "CLEAR_TO_CLOSE"


class DocType(str, Enum):
    EXECUTED_CONTRACT = "EXECUTED_CONTRACT"
    INSPECTION_REPORT = "INSPECTION_REPORT"
    APPRAISAL_REPORT = "APPRAISAL_REPORT"
    LOAN_COMMITMENT = "LOAN_COMMITMENT"
    TITLE_COMMITMENT = "TITLE_COMMITMENT"
    T47_DISCLOSURE = "T47_DISCLOSURE"
    NHD_REPORT = "NHD_REPORT"
    TDS_DISCLOSURE = "TDS_DISCLOSURE"
    HOA_ADDENDUM = "HOA_ADDENDUM"
    CLOSING_DISCLOSURE = "CLOSING_DISCLOSURE"
    AMENDMENT_EXECUTED = "AMENDMENT_EXECUTED"
    OTHER = "OTHER"


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    COORDINATOR = "Coordinator"
    AGENT = "Agent"
    TITLE_REP = "TitleRep"
    LENDER_REP = "LenderRep"


class Coordinator(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    license_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    coordinator_id: str
    full_name: str
    email: str
    brokerage: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChecklistTemplate(TypedDict, total=False):
    id: str
    state_code: str
    contract_type: str
    milestone_defs: List[dict]
    required_doc_types: List[str]
    status: str
    template_version: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    coordinator_id: str
    monthly_fee_cents: int
    included_files_quota: int
    overage_fee_cents: int
    included_files_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransactionFile(TypedDict, total=False):
    id: str
    coordinator_id: str
    buyer_agent_id: Optional[str]
    seller_agent_id: str
    subscription_id: Optional[str]
    billing_model: str
    state_code: str
    contract_type: str
    property_address: str
    effective_date: str
    closing_date: str
    inspection_offset_days: int
    appraisal_offset_days: int
    financing_offset_days: Optional[int]
    list_price_cents: int
    template_id: Optional[str]
    template_version: Optional[int]
    fee_estimate_cents: Optional[int]
    fee_final_cents: Optional[int]
    last_audit_status: str
    open_escalation_count: int
    status: str
    terminated_reason: Optional[str]
    archived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict, total=False):
    id: str
    file_id: str
    name: str
    offset_days: int
    mandatory: bool
    due_date: str
    status: str
    completed_at: Optional[str]
    late_completion: bool
    created_at: str
    updated_at: str
    version: int


class Deadline(TypedDict, total=False):
    id: str
    file_id: str
    kind: str
    offset_days: int
    day_convention: str
    due_date: str
    status: str
    met_at: Optional[str]
    escalated: bool
    created_at: str
    updated_at: str
    version: int


class Reminder(TypedDict, total=False):
    id: str
    deadline_id: str
    sequence_no: int
    scheduled_at: str
    sent_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Document(TypedDict, total=False):
    id: str
    file_id: str
    doc_type: str
    status: str
    submitted_by_agent_id: Optional[str]
    review_round: int
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommunicationEntry(TypedDict, total=False):
    # Append-only event entity: carries only id + created_at (no updated_at, no version).
    id: str
    file_id: str
    entry_kind: str
    author_role: str
    party: str
    direction: str
    body: str
    requires_response: bool
    response_due_at: Optional[str]
    in_reply_to_id: Optional[str]
    status: str
    created_at: str


class Amendment(TypedDict, total=False):
    id: str
    file_id: str
    round_number: int
    new_effective_date: Optional[str]
    new_closing_date: Optional[str]
    new_list_price_cents: Optional[int]
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SignatureRequest(TypedDict, total=False):
    id: str
    amendment_id: str
    agent_id: str
    signer_party: str
    round_number: int
    status: str
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClosingVerification(TypedDict, total=False):
    id: str
    file_id: str
    title_status: str
    lender_status: str
    overall_status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    file_id: str
    subscription_id: Optional[str]
    line_items: List[dict]
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
