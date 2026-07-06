"""Domain types: entity TypedDicts, status enums, role enum.

Field names and enum values mirror the PRD's resource definitions exactly.
All entities in this PRD carry the full common-field set (id, created_at,
updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    RESIDENT = "Resident"
    MODERATOR = "Moderator"
    BUSINESS_OWNER = "BusinessOwner"
    AGENCY_OFFICER = "AgencyOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


# --------------------------------------------------------------------------- enums
class SafetyPosture(str, Enum):
    OPEN = "OPEN"
    ELEVATED = "ELEVATED"
    EMERGENCY = "EMERGENCY"


class StateCode(str, Enum):
    CA = "CA"
    NY = "NY"
    TX = "TX"
    WA = "WA"
    IL = "IL"
    MA = "MA"
    FL = "FL"
    OR = "OR"


class VerificationState(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    RESUBMISSION_REQUIRED = "RESUBMISSION_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ProofType(str, Enum):
    UTILITY_BILL = "UTILITY_BILL"
    LEASE = "LEASE"
    POSTCARD_CODE = "POSTCARD_CODE"
    GEOSTAMP_SELFIE = "GEOSTAMP_SELFIE"


class ResidentVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REVOKED = "REVOKED"


class PostCategory(str, Enum):
    GENERAL = "GENERAL"
    SAFETY = "SAFETY"
    RECOMMENDATION = "RECOMMENDATION"
    LOST_FOUND = "LOST_FOUND"
    FREE_ITEM = "FREE_ITEM"
    QUESTION = "QUESTION"
    ANNOUNCEMENT = "ANNOUNCEMENT"


class PostState(str, Enum):
    PUBLISHED = "PUBLISHED"
    FLAGGED = "FLAGGED"
    HIDDEN = "HIDDEN"
    REMOVED = "REMOVED"


class MarketplaceListingState(str, Enum):
    ACTIVE = "ACTIVE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"
    SUSPENDED = "SUSPENDED"


class MarketplaceListingKind(str, Enum):
    FOR_SALE = "FOR_SALE"
    FREE = "FREE"
    WANTED = "WANTED"
    RECOMMENDATION = "RECOMMENDATION"


class IncidentSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class IncidentCategory(str, Enum):
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
    PROPERTY_CRIME = "PROPERTY_CRIME"
    TRAFFIC_HAZARD = "TRAFFIC_HAZARD"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    PERSON_MISSING = "PERSON_MISSING"
    ANIMAL = "ANIMAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class CivicNoticeKind(str, Enum):
    POLICE = "POLICE"
    FIRE = "FIRE"
    PUBLIC_WORKS = "PUBLIC_WORKS"
    HEALTH = "HEALTH"
    ELECTION = "ELECTION"


class CivicNoticeState(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RETRACTED = "RETRACTED"
    EXPIRED = "EXPIRED"


class FlagTargetType(str, Enum):
    POST = "POST"
    MARKETPLACE_LISTING = "MARKETPLACE_LISTING"
    INCIDENT = "INCIDENT"
    CIVIC_NOTICE = "CIVIC_NOTICE"
    EVENT = "EVENT"


class FlagReason(str, Enum):
    SPAM = "SPAM"
    HARASSMENT = "HARASSMENT"
    MISINFORMATION = "MISINFORMATION"
    PROHIBITED = "PROHIBITED"
    OFF_TOPIC = "OFF_TOPIC"
    PRIVACY = "PRIVACY"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    REVERSED = "REVERSED"


class ModerationDecisionKind(str, Enum):
    UPHOLD = "UPHOLD"
    DISMISS = "DISMISS"
    REVERSE = "REVERSE"


class BusinessState(str, Enum):
    CLAIMED = "CLAIMED"
    VERIFIED_BUSINESS = "VERIFIED_BUSINESS"
    DISPUTED = "DISPUTED"
    DELISTED = "DELISTED"


class LocalAdState(str, Enum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    EXHAUSTED = "EXHAUSTED"
    ENDED = "ENDED"


class EventState(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class RSVPStatus(str, Enum):
    YES = "YES"
    NO = "NO"
    MAYBE = "MAYBE"


# --------------------------------------------------------------------------- entities
class Neighborhood(TypedDict):
    id: str
    name: str
    state_code: str
    center_lat: float
    center_lng: float
    radius_meters: int
    safety_posture: str
    unresolved_critical_count: int
    verified_resident_count: int
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    email: str
    display_name: str
    home_address_line: str
    home_lat: float
    home_lng: float
    primary_neighborhood_id: str
    is_moderator: bool
    trust_score: int
    verification_status: str
    is_suspended: bool
    created_at: str
    updated_at: str
    version: int


class VerificationRequest(TypedDict):
    id: str
    resident_id: str
    neighborhood_id: str
    proof_type: str
    proof_reference: str
    state: str
    reviewer_moderator_id: Optional[str]
    submitted_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class ResidentMembership(TypedDict):
    id: str
    resident_id: str
    neighborhood_id: str
    status: str
    verified_at: Optional[str]
    source_verification_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Post(TypedDict):
    id: str
    author_resident_id: str
    neighborhood_id: str
    category: str
    title: str
    body: str
    state: str
    flag_count: int
    local_relevance_score: float
    created_at: str
    updated_at: str
    version: int


class MarketplaceListing(TypedDict):
    id: str
    seller_resident_id: str
    neighborhood_id: str
    title: str
    price_cents: int
    kind: str
    state: str
    reserved_for_resident_id: Optional[str]
    reserved_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    reporter_resident_id: str
    neighborhood_id: str
    incident_lat: float
    incident_lng: float
    severity: str
    category: str
    description: str
    status: str
    acknowledged_by_officer_id: Optional[str]
    occurred_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CivicNotice(TypedDict):
    id: str
    agency_officer_id: str
    neighborhood_id: str
    title: str
    body: str
    notice_kind: str
    effective_from: str
    effective_until: str
    state: str
    created_at: str
    updated_at: str
    version: int


class FlagReport(TypedDict):
    id: str
    reporter_resident_id: str
    target_type: str
    target_id: str
    reason: str
    status: str
    linked_decision_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModerationDecision(TypedDict):
    id: str
    moderator_resident_id: str
    flag_report_id: str
    decision: str
    rationale: str
    expected_target_version: int
    trust_delta_applied: int
    created_at: str
    updated_at: str
    version: int


class Business(TypedDict):
    id: str
    owner_resident_id: str
    name: str
    address_line: str
    business_lat: float
    business_lng: float
    primary_neighborhood_id: str
    recommendation_count: int
    state: str
    created_at: str
    updated_at: str
    version: int


class LocalAd(TypedDict):
    id: str
    business_id: str
    target_neighborhood_ids: List[str]
    budget_cents: int
    spend_cents: int
    bid_cents_per_impression: int
    state: str
    start_at: str
    end_at: str
    created_at: str
    updated_at: str
    version: int


class Group(TypedDict):
    id: str
    creator_resident_id: str
    neighborhood_id: str
    name: str
    is_private: bool
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    group_id: str
    neighborhood_id: str
    title: str
    venue_lat: float
    venue_lng: float
    starts_at: str
    ends_at: str
    capacity: int
    rsvp_count: int
    state: str
    created_at: str
    updated_at: str
    version: int


class EventRSVP(TypedDict):
    id: str
    event_id: str
    resident_id: str
    rsvp_status: str
    created_at: str
    updated_at: str
    version: int
