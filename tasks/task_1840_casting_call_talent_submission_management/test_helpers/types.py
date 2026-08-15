"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the full common field set (id, created_at, updated_at,
version) per PRD section 2.5: "No entity in this domain is exempt: all
resources carry the full common set".
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    CASTING_DIRECTOR = "CastingDirector"
    CASTING_ASSOCIATE = "CastingAssociate"
    AGENT = "Agent"
    PRODUCTION_COORDINATOR = "ProductionCoordinator"
    GUARDIAN = "Guardian"


class ProductionStatus(str, Enum):
    SETUP = "SETUP"
    CASTING = "CASTING"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"


class ProductionType(str, Enum):
    FILM = "FILM"
    TV_SERIES = "TV_SERIES"
    COMMERCIAL = "COMMERCIAL"
    THEATER = "THEATER"
    NEW_MEDIA = "NEW_MEDIA"


class BreakdownStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED_AGENT_ONLY = "RELEASED_AGENT_ONLY"
    RELEASED_OPEN = "RELEASED_OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Distribution(str, Enum):
    AGENT_ONLY = "AGENT_ONLY"
    OPEN_CALL = "OPEN_CALL"


class RoleStatus(str, Enum):
    OPEN = "OPEN"
    CAST = "CAST"
    CANCELLED = "CANCELLED"


class UnionStatus(str, Enum):
    UNION_MEMBER = "UNION_MEMBER"
    NON_UNION = "NON_UNION"
    ELIGIBLE_PENDING = "ELIGIBLE_PENDING"


class FranchiseStatus(str, Enum):
    FRANCHISED = "FRANCHISED"
    NON_FRANCHISED = "NON_FRANCHISED"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SHORTLISTED = "SHORTLISTED"
    REJECTED = "REJECTED"
    CALLBACK_INVITED = "CALLBACK_INVITED"
    CALLBACK_COMPLETED = "CALLBACK_COMPLETED"
    OFFER_PENDING = "OFFER_PENDING"
    BOOKED = "BOOKED"
    NOT_BOOKED = "NOT_BOOKED"
    WITHDRAWN = "WITHDRAWN"


class SubmittedVia(str, Enum):
    AGENT = "AGENT"
    SELF = "SELF"


class SelfTapeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AppointmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class HoldKind(str, Enum):
    PIN = "PIN"
    AVAIL = "AVAIL"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    OUTBID = "OUTBID"


class OfferStatus(str, Enum):
    EXTENDED = "EXTENDED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ProrationMode(str, Enum):
    CALENDAR_SPAN = "CALENDAR_SPAN"
    WORKDAY_SPAN = "WORKDAY_SPAN"


class DealMemoStatus(str, Enum):
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class PermitStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CancellationReason(str, Enum):
    PRODUCTION_CANCELLED = "PRODUCTION_CANCELLED"
    TALENT_CANCELLED = "TALENT_CANCELLED"
    FORCE_MAJEURE = "FORCE_MAJEURE"
    PERMIT_REVOKED = "PERMIT_REVOKED"


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class TaftHartleyStatus(str, Enum):
    PENDING = "PENDING"
    FILED = "FILED"
    LATE = "LATE"
    WAIVED = "WAIVED"


class ReasonCode(str, Enum):
    SPECIAL_SKILL = "SPECIAL_SKILL"
    FIRST_EMPLOYMENT = "FIRST_EMPLOYMENT"
    EXIGENCY = "EXIGENCY"


class Production(TypedDict, total=False):
    id: str
    title: str
    production_type: str
    union_signatory: bool
    shoot_city: str
    shoot_state: str
    start_date: str
    wrap_date: str
    casting_office_id: str
    status: str
    active_breakdown_count: int
    created_at: str
    updated_at: str
    version: int


class Role(TypedDict, total=False):
    id: str
    production_id: str
    character_name: str
    is_minor_role: bool
    is_union_covered: bool
    engagement_start: str
    engagement_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Breakdown(TypedDict, total=False):
    id: str
    production_id: str
    role_id: str
    distribution: str
    submission_deadline: str
    rate_weekly_cents: int
    status: str
    released_at: Optional[str]
    submission_count: int
    created_at: str
    updated_at: str
    version: int


class Talent(TypedDict, total=False):
    id: str
    full_name: str
    stage_name: Optional[str]
    date_of_birth: str
    is_minor: bool
    union_status: str
    agent_id: Optional[str]
    union_engagement_count_365d: int
    created_at: str
    updated_at: str
    version: int


class AgentProfile(TypedDict, total=False):
    id: str
    agency_name: str
    contact_email: str
    franchise_status: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Guardian(TypedDict, total=False):
    id: str
    full_name: str
    contact_email: str
    relationship: str
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict, total=False):
    id: str
    breakdown_id: str
    talent_id: str
    agent_id: Optional[str]
    submitted_via: str
    status: str
    duplicate_of_id: Optional[str]
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SelfTape(TypedDict, total=False):
    id: str
    submission_id: str
    media_url: str
    duration_seconds: int
    tape_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditionSession(TypedDict, total=False):
    id: str
    breakdown_id: str
    session_start: str
    session_end: str
    capacity: int
    location: str
    status: str
    booked_count: int
    created_at: str
    updated_at: str
    version: int


class CallbackAppointment(TypedDict, total=False):
    id: str
    session_id: str
    submission_id: str
    slot_start: str
    slot_end: str
    status: str
    buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class AvailabilityHold(TypedDict, total=False):
    id: str
    submission_id: str
    talent_id: str
    hold_kind: str
    window_start: str
    window_end: str
    priority_rank: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    submission_id: str
    weekly_rate_cents: int
    guarantee_cents: int
    round_number: int
    status: str
    expires_at: str
    parent_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DealMemo(TypedDict, total=False):
    id: str
    offer_id: str
    engagement_start: str
    engagement_end: str
    proration_mode: str
    computed_fee_cents: int
    cancellation_penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MinorWorkPermit(TypedDict, total=False):
    id: str
    talent_id: str
    production_id: str
    permit_number: str
    issued_at: str
    valid_until: str
    max_daily_hours_school_day: int
    max_daily_hours_non_school_day: int
    guardian_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    submission_id: str
    deal_memo_id: str
    work_permit_id: Optional[str]
    confirmed_at: Optional[str]
    cancelled_at: Optional[str]
    cancellation_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TaftHartleyReport(TypedDict, total=False):
    id: str
    production_id: str
    talent_id: str
    booking_id: str
    reason_code: str
    filing_deadline: str
    filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
