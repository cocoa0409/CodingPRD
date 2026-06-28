"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3).

Every primary entity carries the full common-field set — id, created_at,
updated_at, version — per PRD §2.4 ("all of them expose `updated_at` and
`version`; none is a create-only record that omits them").
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SCHEDULE_COORDINATOR = "ScheduleCoordinator"
    REPORTER = "Reporter"
    ATTORNEY = "Attorney"
    BILLING_CLERK = "BillingClerk"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Enumerations (PRD §3)
# ---------------------------------------------------------------------------
class Jurisdiction(str, Enum):
    FEDERAL = "FEDERAL"
    STATE_CA = "STATE_CA"
    STATE_NY = "STATE_NY"
    STATE_TX = "STATE_TX"


class BarState(str, Enum):
    CA = "CA"
    NY = "NY"
    TX = "TX"
    FED = "FED"


class ResourceKind(str, Enum):
    REPORTER = "REPORTER"
    VIDEOGRAPHER = "VIDEOGRAPHER"
    INTERPRETER = "INTERPRETER"


class JobStatus(str, Enum):
    NOTICED = "NOTICED"
    CONFIRMED = "CONFIRMED"
    IN_SESSION = "IN_SESSION"
    ADJOURNED = "ADJOURNED"
    CANCELLED = "CANCELLED"


class StaffingPosture(str, Enum):
    UNSTAFFED = "UNSTAFFED"
    PARTIAL = "PARTIAL"
    READY = "READY"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class StreamStatus(str, Enum):
    STARTING = "STARTING"
    LIVE = "LIVE"
    STOPPED = "STOPPED"


class TurnaroundTier(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITE_14 = "EXPEDITE_14"
    EXPEDITE_7 = "EXPEDITE_7"
    EXPEDITE_3 = "EXPEDITE_3"
    DAILY = "DAILY"


class TranscriptStatus(str, Enum):
    ORDERED = "ORDERED"
    ROUGH_DELIVERED = "ROUGH_DELIVERED"
    CERTIFIED = "CERTIFIED"
    READ_SIGN_OPEN = "READ_SIGN_OPEN"
    ERRATA_FILED = "ERRATA_FILED"
    SIGNED = "SIGNED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all primary entities carry common fields (PRD §2.4)
# ---------------------------------------------------------------------------
class Case(TypedDict):
    id: str
    caption: str
    docket_number: str
    jurisdiction: str
    noticing_attorney_id: str
    created_at: str
    updated_at: str
    version: int


class Attorney(TypedDict):
    id: str
    full_name: str
    firm_name: str
    bar_state: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Resource(TypedDict):
    id: str
    full_name: str
    kind: str
    certifications: List[str]
    realtime_capable: bool
    hourly_appearance_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict):
    id: str
    case_id: str
    deponent_name: str
    scheduled_start: str
    scheduled_end: str
    requires_videographer: bool
    requires_interpreter: bool
    interpreter_language: Optional[str]
    requires_realtime: bool
    status: str
    staffing_posture: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    job_id: str
    resource_id: str
    role: str
    status: str
    appearance_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class RealtimeStream(TypedDict):
    id: str
    job_id: str
    reporter_assignment_id: str
    access_token: Optional[str]
    status: str
    started_at: Optional[str]
    stopped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TranscriptOrder(TypedDict):
    id: str
    job_id: str
    ordering_attorney_id: str
    turnaround_tier: str
    certified_copy: bool
    estimated_pages: int
    final_pages: Optional[int]
    status: str
    read_sign_deadline: Optional[str]
    errata_round: int
    created_at: str
    updated_at: str
    version: int


class Exhibit(TypedDict):
    id: str
    transcript_order_id: str
    marked_label: str
    page_count: int
    confidential: bool
    created_at: str
    updated_at: str
    version: int


class Errata(TypedDict):
    id: str
    transcript_order_id: str
    round: int
    corrections: List[dict]
    reason: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    job_id: str
    transcript_order_id: str
    bill_to_attorney_id: str
    appearance_subtotal_cents: int
    page_subtotal_cents: int
    exhibit_subtotal_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
