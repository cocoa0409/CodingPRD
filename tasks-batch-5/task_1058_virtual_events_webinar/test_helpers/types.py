"""Domain types for the Virtual-Events & Webinar Platform API.

Entity TypedDicts, status enums and the role enum. Every entity on this
platform carries the four common properties (``id``, ``created_at``,
``updated_at``, ``version``) described in the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ORGANIZER = "Organizer"
    FINANCE_ADMIN = "FinanceAdmin"
    ATTENDEE = "Attendee"
    SPEAKER_USER = "SpeakerUser"
    SPONSOR_USER = "SponsorUser"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------

class EventState(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LIVE = "LIVE"
    ENDED = "ENDED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class TicketTier(str, Enum):
    GENERAL = "GENERAL"
    VIP = "VIP"
    SPONSOR = "SPONSOR"
    SPEAKER = "SPEAKER"


class GatingLevel(str, Enum):
    LIVE_ONLY = "LIVE_ONLY"
    ON_DEMAND = "ON_DEMAND"
    BOTH = "BOTH"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SOLD_OUT = "SOLD_OUT"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class AttendanceStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    WITHDRAWN = "WITHDRAWN"


class SessionState(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SessionType(str, Enum):
    LIVE = "LIVE"
    SIMULIVE = "SIMULIVE"
    ON_DEMAND = "ON_DEMAND"


class EngagementStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ENGAGED = "ENGAGED"


class SpeakingRole(str, Enum):
    HOST = "HOST"
    PANELIST = "PANELIST"
    MODERATOR = "MODERATOR"


class SessionSpeakerState(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    RELEASED = "RELEASED"


class IngestRegion(str, Enum):
    US_EAST = "US_EAST"
    US_WEST = "US_WEST"
    EU_WEST = "EU_WEST"
    AP_SOUTH = "AP_SOUTH"


class BroadcastState(str, Enum):
    SCHEDULED = "SCHEDULED"
    PREVIEW = "PREVIEW"
    LIVE = "LIVE"
    ENDED = "ENDED"
    ABORTED = "ABORTED"


class RecordingState(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"
    DELETED = "DELETED"


class PackageTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ContractStatus(str, Enum):
    UNSIGNED = "UNSIGNED"
    SIGNED = "SIGNED"


class BoothState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"


class InteractionType(str, Enum):
    VISIT = "VISIT"
    DOWNLOAD = "DOWNLOAD"


class ScoreVariant(str, Enum):
    BOOTH_WEIGHTED = "BOOTH_WEIGHTED"
    ENGAGEMENT_WEIGHTED = "ENGAGEMENT_WEIGHTED"


class MatchRequestState(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SettlementSubjectType(str, Enum):
    EVENT = "EVENT"
    SPONSOR = "SPONSOR"


class SettlementState(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------

class Event(TypedDict):
    id: str
    organizer_user_id: str
    name: str
    timezone: str
    starts_at: str
    ends_at: str
    early_bird_ends_at: str
    capacity: int
    state: str
    registered_count: int
    gross_collected_cents: int
    streamed_minutes_total: int
    published_recording_count: int
    settlement_adjustment_cents: int
    created_at: str
    updated_at: str
    version: int


class TicketType(TypedDict):
    id: str
    event_id: str
    name: str
    tier: str
    price_cents: int
    quota: int
    gating_level: str
    sold_count: int
    availability_status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    event_id: str
    ticket_type_id: str
    attendee_email: str
    group_code: Optional[str]
    group_size: int
    payment_status: str
    attendance_status: str
    amount_due_cents: int
    amount_paid_cents: int
    final_amount_due_cents: Optional[int]
    watched_minutes: int
    accepted_meeting_count: int
    created_at: str
    updated_at: str
    version: int


class Track(TypedDict):
    id: str
    event_id: str
    name: str
    scheduled_session_count: int
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    event_id: str
    track_id: str
    title: str
    starts_at: str
    ends_at: str
    session_type: str
    capacity: int
    state: str
    accepted_speaker_count: int
    created_at: str
    updated_at: str
    version: int


class Speaker(TypedDict):
    id: str
    event_id: str
    full_name: str
    email: str
    accepted_session_count: int
    engagement_status: str
    created_at: str
    updated_at: str
    version: int


class SessionSpeaker(TypedDict):
    id: str
    session_id: str
    speaker_id: str
    speaking_role: str
    state: str
    invite_round: int
    created_at: str
    updated_at: str
    version: int


class Broadcast(TypedDict):
    id: str
    session_id: str
    ingest_region: str
    state: str
    started_at: Optional[str]
    ended_at: Optional[str]
    streamed_minutes: int
    created_at: str
    updated_at: str
    version: int


class Recording(TypedDict):
    id: str
    broadcast_id: str
    session_id: str
    event_id: str
    state: str
    duration_seconds: int
    gating_level: str
    view_count: int
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict):
    id: str
    event_id: str
    name: str
    package_tier: str
    contact_email: str
    contract_status: str
    created_at: str
    updated_at: str
    version: int


class Booth(TypedDict):
    id: str
    sponsor_id: str
    event_id: str
    headline: str
    lead_quota: int
    state: str
    captured_lead_count: int
    stream_minutes_total: int
    revision_round: int
    created_at: str
    updated_at: str
    version: int


class Lead(TypedDict):
    id: str
    booth_id: str
    registration_id: str
    event_id: str
    marketing_consent: bool
    booth_visits: int
    doc_downloads: int
    score: int
    score_variant: str
    is_hot: bool
    created_at: str
    updated_at: str
    version: int


class MatchRequest(TypedDict):
    id: str
    event_id: str
    requester_registration_id: str
    target_registration_id: str
    window_start: str
    window_end: str
    expires_at: str
    state: str
    created_at: str
    updated_at: str
    version: int


class SettlementLineItem(TypedDict):
    label: str
    units: int
    unit_cents: Any
    line_total_cents: int


class Settlement(TypedDict):
    id: str
    event_id: str
    sponsor_id: Optional[str]
    subject_type: str
    state: str
    line_items: List[SettlementLineItem]
    subtotal_cents: int
    tax_cents: int
    platform_fee_cents: int
    total_cents: int
    organizer_payout_cents: int
    issued_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
