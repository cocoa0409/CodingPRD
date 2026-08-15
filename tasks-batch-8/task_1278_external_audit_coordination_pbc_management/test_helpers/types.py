"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class EngagementStatus(str, Enum):
    PLANNING = "PLANNING"
    FIELDWORK = "FIELDWORK"
    FIELDWORK_COMPLETE = "FIELDWORK_COMPLETE"
    REPORT_ISSUED = "REPORT_ISSUED"
    CANCELLED = "CANCELLED"


class EngagementPosture(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    LOCKED = "LOCKED"


class PBCRequestStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FROZEN = "FROZEN"


class EvidenceUploadStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


class QueryStatus(str, Enum):
    OPEN = "OPEN"
    AWAITING_CLIENT = "AWAITING_CLIENT"
    RESPONDED = "RESPONDED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class QuerySeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SamplingRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class FieldworkVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AdjustmentDisposition(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PASSED = "PASSED"


class AdjustmentDirection(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class RepresentationLetterStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    SIGNED = "SIGNED"


class FeeChangeRequestStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class FeeProposerRole(str, Enum):
    CONTROLLER_OFFICE = "CONTROLLER_OFFICE"
    AUDITOR = "AUDITOR"


class UserRole(str, Enum):
    CONTROLLER = "Controller"
    PREPARER = "Preparer"
    EXTERNAL_AUDITOR = "ExternalAuditor"


# --- Entity TypedDicts ---
# PRD §2.4: every resource carries id, created_at, updated_at, and version —
# "No entity in this domain is exempt from this convention; all ten resource
# types carry all four fields."


class AuditEngagement(TypedDict, total=False):
    id: str
    client_name: str
    fiscal_year_end: str
    base_fee_cents: int
    materiality_cents: int
    filing_deadline: str
    total_fee_cents: int
    open_pbc_count: int
    open_query_count: int
    passed_adjustment_total_cents: int
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict, total=False):
    id: str
    engagement_id: str
    location_code: str
    name: str
    materiality_cents: int
    created_at: str
    updated_at: str
    version: int


class PBCRequest(TypedDict, total=False):
    id: str
    engagement_id: str
    title: str
    owner_user_id: str
    due_date: str
    current_evidence_id: Optional[str]
    rejection_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EvidenceUpload(TypedDict, total=False):
    id: str
    pbc_request_id: str
    engagement_id: str
    uploader_user_id: str
    version_seq: int
    file_name: str
    file_size_bytes: int
    sha256: str
    uploaded_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditorQuery(TypedDict, total=False):
    id: str
    engagement_id: str
    pbc_request_id: Optional[str]
    auditor_user_id: str
    subject: str
    severity: str
    raised_at: str
    responded_at: Optional[str]
    turnaround_hours: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SamplingRequest(TypedDict, total=False):
    id: str
    engagement_id: str
    title: str
    location_ids: List[str]
    window_start: str
    window_end: str
    sample_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FieldworkVisit(TypedDict, total=False):
    id: str
    engagement_id: str
    auditor_user_id: str
    location_id: str
    visit_start: str
    visit_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditAdjustment(TypedDict, total=False):
    id: str
    engagement_id: str
    proposed_by_user_id: str
    description: str
    amount_cents: int
    direction: str
    disposition: str
    disposition_rationale: Optional[str]
    disposition_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepresentationLetter(TypedDict, total=False):
    id: str
    engagement_id: str
    prepared_by_user_id: Optional[str]
    signed_by_user_id: Optional[str]
    signed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeChangeRequest(TypedDict, total=False):
    id: str
    engagement_id: str
    proposed_by_role: str
    scope_description: str
    delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
