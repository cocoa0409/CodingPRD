"""Domain types: entity TypedDicts, status enums, role enum.

All enums and field names mirror the PRD's FOIA Information Request API contract.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    REQUESTER = "Requester"
    FOIA_OFFICER = "FoiaOfficer"
    APPEAL_AUTHORITY = "AppealAuthority"
    SUBMITTER = "Submitter"


# ─── Enumerations ─────────────────────────────────────
class FeeCategory(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    EDUCATIONAL = "EDUCATIONAL"
    NEWS_MEDIA = "NEWS_MEDIA"
    OTHER = "OTHER"


class FoiaRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PERFECTED = "PERFECTED"
    PROCESSING = "PROCESSING"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    GRANTED = "GRANTED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
    DENIED = "DENIED"
    GLOMAR_INVOKED = "GLOMAR_INVOKED"
    WITHDRAWN = "WITHDRAWN"


class DeadlineStatus(str, Enum):
    RUNNING = "RUNNING"
    TOLLED = "TOLLED"
    EXTENDED = "EXTENDED"
    MET = "MET"
    MISSED = "MISSED"


class FeePaymentStatus(str, Enum):
    NONE = "NONE"
    DUE = "DUE"
    PAID = "PAID"
    WAIVED = "WAIVED"


class GlomarExemptionBasis(str, Enum):
    B1 = "B1"
    B7 = "B7"


class RecordDisposition(str, Enum):
    PENDING = "PENDING"
    RELEASABLE = "RELEASABLE"
    REDACTED = "REDACTED"
    WITHHELD = "WITHHELD"


class ExemptionAppliesToKind(str, Enum):
    RECORD = "RECORD"
    REQUEST = "REQUEST"


class ExemptionCode(str, Enum):
    B1 = "B1"
    B2 = "B2"
    B3 = "B3"
    B4 = "B4"
    B5 = "B5"
    B6 = "B6"
    B7 = "B7"
    B8 = "B8"
    B9 = "B9"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AFFIRMED = "AFFIRMED"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"


class AppealDecision(str, Enum):
    AFFIRM = "AFFIRM"
    REVERSE = "REVERSE"
    REMAND = "REMAND"


class ObjectionStatus(str, Enum):
    NOTICED = "NOTICED"
    OBJECTED = "OBJECTED"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"
    NO_RESPONSE = "NO_RESPONSE"


class ObjectionResolution(str, Enum):
    SUSTAIN = "SUSTAIN"
    OVERRULE = "OVERRULE"


class AuditEventType(str, Enum):
    SUBMITTED = "SUBMITTED"
    PERFECTED = "PERFECTED"
    ASSIGNED = "ASSIGNED"
    FEE_ASSESSED = "FEE_ASSESSED"
    EXTENDED = "EXTENDED"
    TOLLED = "TOLLED"
    RESUMED = "RESUMED"
    DETERMINATION = "DETERMINATION"
    GLOMAR = "GLOMAR"
    APPEAL_FILED = "APPEAL_FILED"
    APPEAL_DECIDED = "APPEAL_DECIDED"
    REVERSE_NOTICE = "REVERSE_NOTICE"
    REVERSE_DECIDED = "REVERSE_DECIDED"


# ─── Entity TypedDicts ────────────────────────────────
# Entities carrying id + created_at + updated_at + version.

class Requester(TypedDict):
    id: str
    full_name: str
    email: str
    organization: Optional[str]
    declared_category: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class FoiaOfficer(TypedDict):
    id: str
    full_name: str
    badge_id: str
    can_invoke_glomar: bool
    created_at: str
    updated_at: str
    version: int


class AppealAuthority(TypedDict):
    id: str
    full_name: str
    badge_id: str
    created_at: str
    updated_at: str
    version: int


class Submitter(TypedDict):
    id: str
    company_name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class FoiaRequest(TypedDict):
    id: str
    requester_id: str
    assigned_officer_id: Optional[str]
    subject_description: str
    fee_category: Optional[str]
    expedited: bool
    fee_waiver_requested: bool
    fee_waiver_granted: bool
    status: str
    deadline_status: str
    glomar_exemption_basis: Optional[str]
    fee_payment_status: str
    received_at: str
    created_at: str
    updated_at: str
    version: int


class ResponsiveRecord(TypedDict):
    id: str
    request_id: str
    title: str
    page_count: int
    contains_submitter_info: bool
    submitter_id: Optional[str]
    disposition: str
    created_at: str
    updated_at: str
    version: int


class FeeEstimate(TypedDict):
    id: str
    request_id: str
    search_hours: float
    review_hours: float
    billable_pages: int
    assessed_fee_cents: int
    requires_advance_payment: bool
    created_at: str
    updated_at: str
    version: int


class ProcessingDeadline(TypedDict):
    id: str
    request_id: str
    base_due_at: str
    extension_days_added: int
    tolled_working_days: int
    effective_due_at: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    request_id: str
    appellant_id: str
    assigned_authority_id: Optional[str]
    grounds: str
    status: str
    filed_at: str
    created_at: str
    updated_at: str
    version: int


class ThirdPartyObjection(TypedDict):
    id: str
    record_id: str
    submitter_id: str
    notice_sent_at: str
    objection_text: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReadingRoom(TypedDict):
    id: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class ReviewStation(TypedDict):
    id: str
    name: str
    buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class ReadingRoomBooking(TypedDict):
    id: str
    room_id: str
    request_id: str
    starts_at: str
    ends_at: str
    created_at: str
    updated_at: str
    version: int


class ReviewStationBooking(TypedDict):
    id: str
    station_id: str
    request_id: str
    starts_at: str
    ends_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only entities carry ONLY id + created_at (no updated_at, no version).

class Exemption(TypedDict):
    id: str
    request_id: str
    record_id: Optional[str]
    applies_to_kind: str
    exemption_code: str
    justification: str
    created_at: str


class AuditEvent(TypedDict):
    id: str
    request_id: str
    event_type: str
    detail: str
    actor_role: str
    created_at: str
