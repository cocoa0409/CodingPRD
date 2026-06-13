"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §4)."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class MatterLifecycleStatus(str, Enum):
    OPEN = "OPEN"
    IN_DISCOVERY = "IN_DISCOVERY"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class MatterHoldStatus(str, Enum):
    NO_HOLD = "NO_HOLD"
    HOLD_ACTIVE = "HOLD_ACTIVE"
    HOLD_RELEASED = "HOLD_RELEASED"


class CustodianAckState(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class LegalHoldStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RELEASED = "RELEASED"


class HoldAcknowledgementStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class CollectionScopeStatus(str, Enum):
    DEFINED = "DEFINED"
    COLLECTING = "COLLECTING"
    COLLECTED = "COLLECTED"
    PROCESSED = "PROCESSED"
    RELEASED = "RELEASED"


class DocumentStatus(str, Enum):
    COLLECTED = "COLLECTED"
    DUPLICATE = "DUPLICATE"
    UNIQUE = "UNIQUE"
    PURGEABLE = "PURGEABLE"


class PrivilegeTag(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    NOT_PRIVILEGED = "NOT_PRIVILEGED"
    PRIVILEGED = "PRIVILEGED"
    REDACTED = "REDACTED"


class ResponsivenessTag(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    RESPONSIVE = "RESPONSIVE"
    NON_RESPONSIVE = "NON_RESPONSIVE"


class ProcessingJobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReviewBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    QC_REVIEW = "QC_REVIEW"
    COMPLETED = "COMPLETED"


class ReviewDecision(str, Enum):
    UNDECIDED = "UNDECIDED"
    RESPONSIVE_NOT_PRIV = "RESPONSIVE_NOT_PRIV"
    RESPONSIVE_PRIV = "RESPONSIVE_PRIV"
    RESPONSIVE_REDACTED = "RESPONSIVE_REDACTED"
    NON_RESPONSIVE = "NON_RESPONSIVE"


class ProductionSetStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    BLOCKED = "BLOCKED"
    STAGED = "STAGED"
    PRODUCED = "PRODUCED"


class ProductionItemStatus(str, Enum):
    STAGED = "STAGED"
    PRODUCED = "PRODUCED"
    CLAWED_BACK = "CLAWED_BACK"


class ClawbackStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SEQUESTERED = "SEQUESTERED"
    DISPUTED = "DISPUTED"


class UserRole(str, Enum):
    LEGAL_OPS = "LegalOps"
    REVIEW_LEAD = "ReviewLead"
    REVIEWER = "Reviewer"
    PRODUCER = "Producer"
    CUSTODIAN = "Custodian"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true entities carry id, created_at, updated_at, version.
# common_fields: false entities (ProductionItem) carry only id + created_at.
# ---------------------------------------------------------------------------
class Matter(TypedDict):
    id: str
    caption: str
    bates_prefix: str
    lifecycle_status: str
    hold_status: str
    custodian_count: int
    acknowledged_count: int
    ack_rate: float
    responsive_doc_count: int
    next_bates_seq: int
    produced_document_count: int
    clawed_back_document_count: int
    spoliation_risk_score: int
    created_at: str
    updated_at: str
    version: int


class Custodian(TypedDict):
    id: str
    matter_id: str
    full_name: str
    email: str
    ack_state: str
    retention_released: bool
    created_at: str
    updated_at: str
    version: int


class LegalHold(TypedDict):
    id: str
    matter_id: str
    title: str
    instructions: str
    status: str
    issued_at: Optional[str]
    ack_deadline: str
    pending_ack_count: int
    created_at: str
    updated_at: str
    version: int


class HoldAcknowledgement(TypedDict):
    id: str
    hold_id: str
    custodian_id: str
    status: str
    acknowledged_at: Optional[str]
    on_time: bool
    created_at: str
    updated_at: str
    version: int


class CollectionScope(TypedDict):
    id: str
    matter_id: str
    custodian_id: str
    source_label: str
    range_start: str
    range_end: str
    expected_doc_count: int
    status: str
    collected_actual_count: int
    created_at: str
    updated_at: str
    version: int


class Document(TypedDict):
    id: str
    scope_id: str
    matter_id: str
    content_hash: str
    page_count: int
    status: str
    privilege_tag: str
    responsiveness_tag: str
    duplicate_of_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcessingJob(TypedDict):
    id: str
    matter_id: str
    scope_id: str
    status: str
    total_input_count: int
    unique_count: int
    duplicate_count: int
    created_at: str
    updated_at: str
    version: int


class ReviewBatch(TypedDict):
    id: str
    matter_id: str
    name: str
    status: str
    document_count: int
    reviewed_count: int
    created_at: str
    updated_at: str
    version: int


class DocumentReview(TypedDict):
    id: str
    batch_id: str
    document_id: str
    reviewer_user_id: Optional[str]
    decision: str
    created_at: str
    updated_at: str
    version: int


class ProductionSet(TypedDict):
    id: str
    matter_id: str
    source_batch_id: str
    status: str
    bates_start: Optional[int]
    bates_end: Optional[int]
    item_count: int
    produced_page_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — only id + created_at (no updated_at, no version)
class ProductionItem(TypedDict):
    id: str
    set_id: str
    document_id: str
    bates_number: Optional[str]
    status: str
    created_at: str


class Clawback(TypedDict):
    id: str
    matter_id: str
    production_item_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int
