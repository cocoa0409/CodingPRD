"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Process Serving & Legal Support PRD (sections 2.4, 3.x).
ServerTerritory is the one immutable join resource (id + created_at only, no
updated_at / version); every other entity carries the full common-field set.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    ADMIN = "Admin"
    DISPATCHER = "Dispatcher"
    CLIENT = "Client"
    SERVER = "Server"
    NOTARY = "Notary"


# ─── Status enums ─────────────────────────────────────────────────────────
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ServerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ServiceRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SERVED = "SERVED"
    NON_EST = "NON_EST"
    FILED = "FILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    REASSIGNED = "REASSIGNED"
    CANCELLED = "CANCELLED"


class AttemptOutcome(str, Enum):
    NO_ANSWER = "NO_ANSWER"
    EVADED = "EVADED"
    BAD_ADDRESS = "BAD_ADDRESS"
    CONTACT_MADE = "CONTACT_MADE"


class ServiceType(str, Enum):
    PERSONAL = "PERSONAL"
    SUBSTITUTE = "SUBSTITUTE"
    POSTING = "POSTING"


class AffidavitStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    NOTARIZED = "NOTARIZED"
    FILED = "FILED"
    VOID = "VOID"


class SkipTraceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    LOCATED = "LOCATED"
    NOT_LOCATED = "NOT_LOCATED"


class StakeoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FilingStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DocType(str, Enum):
    SUMMONS = "SUMMONS"
    SUBPOENA = "SUBPOENA"
    COMPLAINT = "COMPLAINT"
    NOTICE = "NOTICE"
    WRIT = "WRIT"


class InvoiceLineKind(str, Enum):
    BASE = "BASE"
    RUSH = "RUSH"
    ATTEMPT = "ATTEMPT"
    SKIP_TRACE = "SKIP_TRACE"
    STAKEOUT = "STAKEOUT"
    FILING = "FILING"
    PRINTING = "PRINTING"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version)
class Client(TypedDict):
    id: str
    firm_name: str
    email: str
    prepaid_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class County(TypedDict):
    id: str
    name: str
    state_code: str
    e_file_enabled: bool
    min_diligent_attempts: int
    filing_fee_cents: int
    max_concurrent_filings: int
    created_at: str
    updated_at: str
    version: int


class Server(TypedDict):
    id: str
    full_name: str
    license_no: str
    max_active_assignments: int
    active_assignment_count: int
    completed_count: int
    reliability_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    client_id: str
    county_id: str
    recipient_name: str
    service_address: str
    service_lat: float
    service_lng: float
    rush: bool
    deadline_utc: Optional[str]
    skip_trace_requested: bool
    assignment_id: Optional[str]
    service_type: Optional[str]
    distinct_attempt_days: int
    quoted_fee_cents: int
    final_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Document(TypedDict):
    id: str
    service_request_id: str
    doc_type: str
    page_count: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    service_request_id: str
    server_id: str
    superseded: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Attempt(TypedDict):
    id: str
    assignment_id: str
    service_request_id: str
    attempted_at_utc: str
    gps_lat: float
    gps_lng: float
    outcome: str
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class Service(TypedDict):
    id: str
    service_request_id: str
    assignment_id: str
    service_type: str
    recipient_relation: str
    served_at_utc: str
    created_at: str
    updated_at: str
    version: int


class Affidavit(TypedDict):
    id: str
    service_request_id: str
    service_id: Optional[str]
    declarant_server_id: str
    notary_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SkipTrace(TypedDict):
    id: str
    service_request_id: str
    candidate_addresses: List[str]
    located_address: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Stakeout(TypedDict):
    id: str
    assignment_id: str
    server_id: str
    window_start_utc: str
    window_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Filing(TypedDict):
    id: str
    service_request_id: str
    county_id: str
    affidavit_id: str
    window_start_utc: str
    window_end_utc: str
    reject_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    id: str
    service_request_id: str
    kind: str
    amount_cents: int
    voided: bool
    created_at: str
    updated_at: str
    version: int


# ─── ServerTerritory (immutable join: id + created_at ONLY) ───────────────
class ServerTerritory(TypedDict):
    id: str
    server_id: str
    county_id: str
    created_at: str
