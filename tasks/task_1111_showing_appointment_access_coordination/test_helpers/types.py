"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    WITHDRAWN = "WITHDRAWN"


class OccupancyType(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"


class ShowingRequestStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CancelActor(str, Enum):
    BUYER_AGENT = "BUYER_AGENT"
    SYSTEM = "SYSTEM"


class CredentialType(str, Enum):
    LOCKBOX_CODE = "LOCKBOX_CODE"
    DOOR_CODE = "DOOR_CODE"
    SMART_LOCK = "SMART_LOCK"


class AccessCredentialStatus(str, Enum):
    ISSUED = "ISSUED"
    USED = "USED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class FeedbackRequestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    SUBMITTED = "SUBMITTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class VerificationCaseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class AgentStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class StrikeType(str, Enum):
    NO_SHOW = "NO_SHOW"
    LATE_CANCEL = "LATE_CANCEL"


class StrikeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FORGIVEN = "FORGIVEN"
    EXPIRED = "EXPIRED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"
    SELLER = "Seller"
    LISTING_AGENT = "ListingAgent"
    BUYER_AGENT = "BuyerAgent"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ReportMode(str, Enum):
    FINAL = "FINAL"
    PROVISIONAL = "PROVISIONAL"


class Seller(TypedDict, total=False):
    id: str
    full_name: str
    contact_email: str
    approval_timeout_minutes: int
    auto_approve: bool
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    brokerage_name: str
    verification_status: str
    standing: str
    active_strike_points: int
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict, total=False):
    id: str
    seller_id: str
    address: str
    occupancy_type: str
    status: str
    buffer_minutes: int
    max_showings_per_day: int
    min_notice_minutes: int
    confirmed_showing_count: int
    avg_feedback_score: float
    created_at: str
    updated_at: str
    version: int


class VerificationCase(TypedDict, total=False):
    id: str
    agent_id: str
    license_document_ref: str
    status: str
    review_notes: Optional[str]
    reviewed_at: Optional[str]
    resubmission_count: int
    created_at: str
    updated_at: str
    version: int


class BlackoutWindow(TypedDict, total=False):
    id: str
    listing_id: str
    start_at: str
    end_at: str
    reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShowingRequest(TypedDict, total=False):
    id: str
    listing_id: str
    buyer_agent_id: str
    start_at: str
    end_at: str
    buyer_name: Optional[str]
    note: Optional[str]
    status: str
    approval_deadline: str
    confirm_by_deadline: str
    decline_reason: Optional[str]
    cancel_actor: Optional[str]
    cancelled_at: Optional[str]
    completed_at: Optional[str]
    reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class AccessCredential(TypedDict, total=False):
    id: str
    showing_request_id: str
    credential_type: str
    access_code: str
    instructions_text: str
    active_from: str
    expires_at: str
    status: str
    redeemed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeedbackRequest(TypedDict, total=False):
    id: str
    showing_request_id: str
    status: str
    sent_at: Optional[str]
    due_at: Optional[str]
    q1: Optional[int]
    q2: Optional[int]
    q3: Optional[int]
    q4: Optional[int]
    q5: Optional[int]
    comment: Optional[str]
    overall_score: Optional[float]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StrikeRecord(TypedDict, total=False):
    id: str
    agent_id: str
    showing_request_id: str
    strike_type: str
    weight: int
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only log record: carries ONLY id + created_at (no updated_at, no version).
class ActivityEvent(TypedDict, total=False):
    id: str
    created_at: str
    listing_id: str
    showing_request_id: Optional[str]
    event_type: str
    actor_role: str
    detail: str
