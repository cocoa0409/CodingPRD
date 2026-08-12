"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the standard system-managed fields described in PRD §2.5
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional


class AlumniRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LOST = "LOST"
    DECEASED = "DECEASED"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"


class ResearchCaseStatus(str, Enum):
    OPEN = "OPEN"
    LEAD_LOGGED = "LEAD_LOGGED"
    VERIFIED = "VERIFIED"
    REUNITED = "REUNITED"
    DEAD_END = "DEAD_END"


class LeadSource(str, Enum):
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    PUBLIC_RECORDS = "PUBLIC_RECORDS"
    PEER_TIP = "PEER_TIP"
    PROFESSIONAL_DATABASE = "PROFESSIONAL_DATABASE"


class ReunionEventStatus(str, Enum):
    PLANNING = "PLANNING"
    COMMITTEE_FORMED = "COMMITTEE_FORMED"
    OPEN_FOR_REGISTRATION = "OPEN_FOR_REGISTRATION"
    HELD = "HELD"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class ReunionPosture(str, Enum):
    GATED = "GATED"
    OPEN = "OPEN"
    SOLD_OUT = "SOLD_OUT"
    CLOSED = "CLOSED"


class MembershipRole(str, Enum):
    CHAIR = "CHAIR"
    TREASURER = "TREASURER"
    LOGISTICS = "LOGISTICS"
    OUTREACH = "OUTREACH"
    MEMBER = "MEMBER"


class MembershipStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    DECLINED = "DECLINED"


class EndedReason(str, Enum):
    RESIGNED = "RESIGNED"
    REMOVED = "REMOVED"
    EVENT_CANCELLED = "EVENT_CANCELLED"
    ALUMNUS_DECEASED = "ALUMNUS_DECEASED"


class PaymentStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    CONFIRMED = "CONFIRMED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class AttendanceStatus(str, Enum):
    NOT_CHECKED_IN = "NOT_CHECKED_IN"
    CHECKED_IN = "CHECKED_IN"


class CancelledReason(str, Enum):
    REGISTRANT = "REGISTRANT"
    EVENT_CANCELLED = "EVENT_CANCELLED"
    ALUMNUS_DECEASED = "ALUMNUS_DECEASED"
    PAYMENT_TIMEOUT = "PAYMENT_TIMEOUT"


class GroupKind(str, Enum):
    AFFINITY = "AFFINITY"
    REGIONAL_CHAPTER = "REGIONAL_CHAPTER"


class GroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISSOLVED = "DISSOLVED"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Channel(str, Enum):
    EMAIL = "EMAIL"
    MAIL = "MAIL"
    PHONE = "PHONE"


class SuppressionReason(str, Enum):
    NONE = "NONE"
    GLOBAL_LIST = "GLOBAL_LIST"
    DO_NOT_CONTACT_RECORD = "DO_NOT_CONTACT_RECORD"
    HARD_BOUNCE = "HARD_BOUNCE"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class PledgeStatus(str, Enum):
    PLEDGED = "PLEDGED"
    FULFILLED = "FULFILLED"
    LAPSED = "LAPSED"
    WRITTEN_OFF = "WRITTEN_OFF"


class PublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


class EngagementTier(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class UserRole(str, Enum):
    ALUMNI_RELATIONS_DIRECTOR = "AlumniRelationsDirector"
    ALUMNI_RELATIONS_STAFF = "AlumniRelationsStaff"
    REUNION_CHAIR = "ReunionChair"
    COMMITTEE_VOLUNTEER = "CommitteeVolunteer"
    AFFINITY_GROUP_LEADER = "AffinityGroupLeader"
    ALUMNI = "Alumni"


class AlumniRecord(TypedDict, total=False):
    id: str
    full_name: str
    primary_email: str
    class_year: int
    degree_code: str
    status: str
    engagement_score: float
    engagement_tier: str
    giving_propensity: float
    lifetime_giving_cents: int
    lost_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LostAlumniResearchCase(TypedDict, total=False):
    id: str
    alumni_id: str
    lead_source: str
    lead_detail: str
    lead_confidence: int
    status: str
    reopened_count: int
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReunionEvent(TypedDict, total=False):
    id: str
    class_year: int
    title: str
    event_date: str
    milestone_year: int
    status: str
    posture: str
    committee_count: int
    committee_quorum_required: int
    total_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class ReunionCommittee(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    chair_membership_id: Optional[str]
    locked: bool
    created_at: str
    updated_at: str
    version: int


class CommitteeMembership(TypedDict, total=False):
    id: str
    committee_id: str
    alumni_id: str
    role: str
    status: str
    invited_at: str
    ended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TicketTier(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    base_price_cents: int
    capacity: int
    sold_count: int
    sales_start: str
    sales_end: str
    early_bird_discount_pct: int
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict, total=False):
    id: str
    event_id: str
    tier_id: str
    alumni_id: str
    payment_status: str
    attendance_status: str
    quoted_price_cents: int
    final_price_cents: int
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AffinityGroup(TypedDict, total=False):
    id: str
    name: str
    kind: str
    status: str
    annual_budget_cents: int
    budget_committed_cents: int
    budget_spent_cents: int
    budget_remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class ChapterProgram(TypedDict, total=False):
    id: str
    group_id: str
    title: str
    venue_slot_start: str
    venue_slot_end: str
    budget_allocated_cents: int
    actual_spend_cents: int
    status: str
    leader_id: str
    created_at: str
    updated_at: str
    version: int


class CommunicationPreference(TypedDict, total=False):
    id: str
    alumni_id: str
    channel: str
    opt_in: bool
    suppressed: bool
    suppression_reason: str
    created_at: str
    updated_at: str
    version: int


class GiftCampaign(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    goal_cents: int
    matching_multiplier_bps: int
    pledged_total_cents: int
    fulfilled_total_cents: int
    matched_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GiftPledge(TypedDict, total=False):
    id: str
    campaign_id: str
    alumni_id: str
    amount_cents: int
    pledge_date: str
    matched_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MemorabiliaPublication(TypedDict, total=False):
    id: str
    event_id: str
    title: str
    class_notes_body: str
    review_round: int
    status: str
    created_at: str
    updated_at: str
    version: int
