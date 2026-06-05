"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PROVIDER = "Provider"
    PAYER = "Payer"
    EXTERNAL_REVIEWER = "ExternalReviewer"


class Specialty(str, Enum):
    CARDIOLOGY = "CARDIOLOGY"
    ONCOLOGY = "ONCOLOGY"
    ORTHOPEDICS = "ORTHOPEDICS"
    NEUROLOGY = "NEUROLOGY"
    PRIMARY_CARE = "PRIMARY_CARE"
    RADIOLOGY = "RADIOLOGY"


class RequestType(str, Enum):
    SERVICE = "SERVICE"
    DRUG = "DRUG"


class AuthorizationRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PENDED = "PENDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class DocumentType(str, Enum):
    CHART_NOTE = "CHART_NOTE"
    LAB_RESULT = "LAB_RESULT"
    IMAGING = "IMAGING"
    MEDICATION_HISTORY = "MEDICATION_HISTORY"
    LETTER_OF_MEDICAL_NECESSITY = "LETTER_OF_MEDICAL_NECESSITY"


class ReviewOutcome(str, Enum):
    APPROVE = "APPROVE"
    PARTIAL = "PARTIAL"
    DENY = "DENY"
    PEND = "PEND"


class PendReason(str, Enum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MISSING_LMN = "MISSING_LMN"
    PEER_TO_PEER_REQUIRED = "PEER_TO_PEER_REQUIRED"


class PeerToPeerSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AppealStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"


class AppealDecision(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


# --- Entities (common_fields: true carry id, created_at, updated_at, version) ---

class Provider(TypedDict):
    id: str
    npi: str
    name: str
    specialty: str
    created_at: str
    updated_at: str
    version: int


class Payer(TypedDict):
    id: str
    name: str
    standard_sla_hours: int
    expedited_sla_hours: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    payer_id: str
    member_number: str
    coinsurance_rate: float
    active_authorization_count: int
    created_at: str
    updated_at: str
    version: int


class AuthorizationRequest(TypedDict):
    id: str
    member_id: str
    provider_id: str
    payer_id: str
    request_type: str
    procedure_code: str
    requested_units: int
    unit_cost_cents: int
    is_expedited: bool
    status: str
    submitted_at: Optional[str]
    review_started_at: Optional[str]
    sla_due_at: Optional[str]
    clock_paused_hours: float
    approved_units: int
    member_cost_share_cents: int
    authorization_expires_at: Optional[str]
    supersedes_request_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class ClinicalEvidence(TypedDict):
    id: str
    request_id: str
    document_type: str
    line_item_cost_cents: int
    uri: str
    created_at: str


class ReviewDecision(TypedDict):
    id: str
    request_id: str
    reviewer_id: str
    outcome: str
    approved_units: int
    rationale: Optional[str]
    pend_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PeerToPeerSession(TypedDict):
    id: str
    request_id: str
    reviewer_id: str
    slot_start: str
    slot_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict):
    id: str
    payer_id: str
    name: str
    specialty: str
    p2p_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    request_id: str
    tier: int
    status: str
    filed_at: str
    appeal_deadline_at: Optional[str]
    decision_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int
