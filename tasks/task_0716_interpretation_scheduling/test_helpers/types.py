"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COORDINATOR_OPS = "CoordinatorOps"
    CLIENT_ACCOUNT = "ClientAccount"
    INTERPRETER = "Interpreter"


# --- Status enums ---
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InterpreterStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    OFFLINE = "OFFLINE"
    DEACTIVATED = "DEACTIVATED"


class RequestStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    UNFULFILLABLE = "UNFULFILLABLE"


class AssignmentLifecycle(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentBilling(str, Enum):
    UNBILLED = "UNBILLED"
    BILLABLE = "BILLABLE"
    INVOICED = "INVOICED"
    WAIVED = "WAIVED"


class SessionStatus(str, Enum):
    CONNECTING = "CONNECTING"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    DISPUTED = "DISPUTED"
    RECONCILED = "RECONCILED"
    CLIENT_NO_SHOW = "CLIENT_NO_SHOW"
    INTERPRETER_NO_SHOW = "INTERPRETER_NO_SHOW"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    VOID = "VOID"


# --- Entity TypedDicts (all entities carry id/created_at/updated_at/version) ---
class ClientAccount(TypedDict):
    id: str
    org_name: str
    org_type: str
    contact_email: str
    status: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RatePlan(TypedDict):
    id: str
    client_id: str
    certification_tier: str
    modality: str
    billing_mode: str
    rate_cents: int
    min_block_units: int
    travel_surcharge_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class LanguagePair(TypedDict):
    id: str
    source_lang: str
    target_lang: str
    rare: bool
    created_at: str
    updated_at: str
    version: int


class Interpreter(TypedDict):
    id: str
    full_name: str
    status: str
    max_concurrent_load: int
    active_load: int
    rating_avg: Optional[float]
    rating_count: int
    acceptance_pct: float
    no_show_strikes: int
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    interpreter_id: str
    tier: str
    expires_at: str
    revoked: bool
    created_at: str
    updated_at: str
    version: int


class InterpreterLanguage(TypedDict):
    id: str
    interpreter_id: str
    language_pair_id: str
    created_at: str
    updated_at: str
    version: int


class InterpretationRequest(TypedDict):
    id: str
    client_id: str
    language_pair_id: str
    modality: str
    required_tier: str
    scheduling_mode: str
    window_start: Optional[str]
    window_end: Optional[str]
    status: str
    cancellation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    request_id: str
    interpreter_id: str
    lifecycle_status: str
    billing_status: str
    offered_at: Optional[str]
    assignment_type: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    assignment_id: str
    status: str
    connected_at: Optional[str]
    ended_at: Optional[str]
    billed_units: int
    billed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict):
    id: str
    session_id: str
    subject_ref: str
    summary: str
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Rating(TypedDict):
    id: str
    session_id: str
    interpreter_id: str
    score: int
    comment: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    session_id: str
    client_id: str
    category: str
    status: str
    remedy_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    client_id: str
    status: str
    line_count: int
    subtotal_cents: int
    fees_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int
