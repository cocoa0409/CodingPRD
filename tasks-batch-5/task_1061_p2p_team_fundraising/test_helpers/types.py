"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CAMPAIGN_MANAGER = "CampaignManager"
    FINANCE_REVIEWER = "FinanceReviewer"
    PARTICIPANT = "Participant"
    DONOR = "Donor"
    ANONYMOUS = "Anonymous"


class PayoutAccountStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class TeamStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISBANDED = "DISBANDED"


class ParticipantStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class RegistrationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class MatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    REVERSED = "REVERSED"


class MatchPoolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class AwardStatus(str, Enum):
    EARNED = "EARNED"
    FULFILLED = "FULFILLED"
    REVOKED = "REVOKED"


class ReceiptStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class PayoutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class DesignationType(str, Enum):
    CAMPAIGN = "CAMPAIGN"
    TEAM = "TEAM"
    PARTICIPANT = "PARTICIPANT"


class LeaderboardScope(str, Enum):
    TEAM = "TEAM"
    PARTICIPANT = "PARTICIPANT"


class LeaderboardVariant(str, Enum):
    RAW_TOTAL = "RAW_TOTAL"
    GOAL_PERCENT = "GOAL_PERCENT"


# All thirteen resource types carry id, created_at, updated_at and version.


class Organization(TypedDict):
    id: str
    name: str
    ein: str
    contact_email: str
    payout_account_status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    organization_id: str
    title: str
    goal_amount_cents: int
    fundraising_minimum_cents: int
    status: str
    published_at: Optional[str]
    closed_at: Optional[str]
    raised_credited_cents: int
    lifetime_net_cents: int
    reserved_payout_cents: int
    paid_out_cents: int
    available_balance_cents: int
    donor_count: int
    receipt_seq: int
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    campaign_id: str
    name: str
    starts_at: str
    ends_at: str
    early_bird_ends_at: str
    registration_fee_cents: int
    capacity: int
    registered_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict):
    id: str
    campaign_id: str
    name: str
    goal_amount_cents: int
    captain_participant_id: Optional[str]
    status: str
    credited_cents: int
    member_count: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    campaign_id: str
    team_id: Optional[str]
    recruited_by_participant_id: Optional[str]
    display_name: str
    personal_goal_cents: int
    status: str
    credited_cents: int
    projected_cents: int
    recruit_count: int
    minimum_met: bool
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    participant_id: str
    event_id: str
    minimum_waived: bool
    fee_charged_cents: int
    status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict):
    id: str
    display_name: str
    email: str
    is_anonymous: bool
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    campaign_id: str
    donor_id: str
    match_pool_id: Optional[str]
    designation_type: str
    designation_id: str
    amount_cents: int
    cover_fees: bool
    benefit_value_cents: int
    fee_cents: int
    net_cents: int
    charged_amount_cents: int
    matched_amount_cents: int
    payment_status: str
    match_status: str
    settled_at: Optional[str]
    refunded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchPool(TypedDict):
    id: str
    campaign_id: str
    sponsor_name: str
    pool_amount_cents: int
    match_ratio: float
    per_donation_cap_cents: int
    min_donation_cents: int
    starts_at: str
    ends_at: str
    allocated_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IncentiveTier(TypedDict):
    id: str
    campaign_id: str
    name: str
    threshold_cents: int
    reward_description: str
    created_at: str
    updated_at: str
    version: int


class IncentiveAward(TypedDict):
    id: str
    participant_id: str
    tier_id: str
    status: str
    earned_at: Optional[str]
    fulfilled_at: Optional[str]
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict):
    id: str
    donation_id: str
    campaign_id: str
    receipt_number: str
    deductible_amount_cents: int
    tax_year: int
    status: str
    issued_at: Optional[str]
    voided_at: Optional[str]
    reissue_count: int
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    campaign_id: str
    amount_cents: int
    note: str
    requested_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
