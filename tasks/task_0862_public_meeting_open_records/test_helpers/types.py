"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API are mutable audit subjects, so every entity carries
id + created_at + updated_at + version (see PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CLERK = "Clerk"
    BODY_MEMBER = "BodyMember"
    RECORDS_OFFICER = "RecordsOfficer"
    APPEALS_OFFICER = "AppealsOfficer"
    REQUESTER = "Requester"
    ANONYMOUS = "Anonymous"


# ---- status enums -----------------------------------------------------------

class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NOTICED = "NOTICED"
    IN_SESSION = "IN_SESSION"
    ADJOURNED = "ADJOURNED"
    CANCELLED = "CANCELLED"


class MinutesStatus(str, Enum):
    NONE = "NONE"
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    AMENDED = "AMENDED"


class AgendaItemStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SpeakerSlipStatus(str, Enum):
    QUEUED = "QUEUED"
    CALLED = "CALLED"
    SPOKEN = "SPOKEN"
    YIELDED = "YIELDED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class MotionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CARRIED = "CARRIED"
    FAILED = "FAILED"
    TABLED = "TABLED"
    VOIDED = "VOIDED"


class MotionOutcome(str, Enum):
    PENDING = "PENDING"
    CARRIED = "CARRIED"
    FAILED = "FAILED"


class RecordsRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class DocumentStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    REVIEWED = "REVIEWED"
    RELEASED = "RELEASED"
    REDACTED = "REDACTED"
    EXEMPT = "EXEMPT"
    DISPOSED = "DISPOSED"
    CANCELLED = "CANCELLED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    REMANDED = "REMANDED"


# ---- entity TypedDicts (all common_fields: true) ----------------------------

class PublicBody(TypedDict):
    id: str
    name: str
    jurisdiction_state: str
    seat_count: int
    quorum_size: int
    created_at: str
    updated_at: str
    version: int


class Requester(TypedDict):
    id: str
    full_name: str
    email: str
    organization: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BodyMember(TypedDict):
    id: str
    body_id: str
    full_name: str
    seat_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    body_id: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class Meeting(TypedDict):
    id: str
    body_id: str
    venue_id: str
    presiding_member_id: str
    title: str
    meeting_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    minutes_status: str
    notice_channel: Optional[str]
    notice_posted_at: Optional[str]
    notice_lead_hours: Optional[float]
    present_member_ids: List[str]
    quorum_met: bool
    minutes_text: Optional[str]
    minutes_approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgendaItem(TypedDict):
    id: str
    meeting_id: str
    title: str
    sequence: int
    item_type: str
    public_comment_enabled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SpeakerSlip(TypedDict):
    id: str
    agenda_item_id: str
    requester_id: str
    speaker_name: str
    allotted_seconds: int
    position: int
    called_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Motion(TypedDict):
    id: str
    agenda_item_id: str
    text: str
    moved_by_member_id: str
    seconded_by_member_id: str
    vote_threshold: str
    ballots: list
    yea_count: int
    nay_count: int
    abstain_count: int
    recused_count: int
    ballot_count: int
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecordsRequest(TypedDict):
    id: str
    requester_id: str
    body_id: str
    subject: str
    description: str
    estimated_page_count: int
    submitted_at: str
    response_deadline: str
    estimated_fee_cents: int
    assessed_fee_cents: int
    amount_waived_cents: int
    amount_paid_cents: int
    fee_balance_cents: int
    decision: str
    determined_by_user_id: Optional[str]
    determined_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ResponsiveDocument(TypedDict):
    id: str
    request_id: str
    title: str
    page_count: int
    review_minutes: int
    exemption_code: str
    retention_series: str
    billable_pages: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    request_id: str
    grounds: str
    filed_at: str
    decided_by_user_id: Optional[str]
    decision: str
    status: str
    created_at: str
    updated_at: str
    version: int
