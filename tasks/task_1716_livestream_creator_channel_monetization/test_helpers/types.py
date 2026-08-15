"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Entities with the standard four
system-managed fields carry id + created_at + updated_at + version;
RevenueEvent is the sole append-only exception and carries only id +
created_at (PRD section on resource identity and timestamps).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CREATOR = "Creator"
    MODERATOR = "Moderator"
    SPONSOR = "Sponsor"
    TRUST_AGENT = "TrustAgent"
    APPEALS_OFFICER = "AppealsOfficer"


class HomePlatform(str, Enum):
    TWITCH = "TWITCH"
    YOUTUBE = "YOUTUBE"


class PayoutSchedule(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class MonetizationPosture(str, Enum):
    STANDARD = "STANDARD"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class TaxFormType(str, Enum):
    W9 = "W9"
    W8BEN = "W8BEN"
    W8BENE = "W8BENE"


class TaxStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RevenueKind(str, Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    TIP = "TIP"
    AD_SHARE = "AD_SHARE"
    SPONSORSHIP = "SPONSORSHIP"
    CHARGEBACK = "CHARGEBACK"


class RecognitionStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    REVERSED = "REVERSED"


class PayoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class HoldReason(str, Enum):
    NONE = "NONE"
    TAX_FORM = "TAX_FORM"
    POSTURE = "POSTURE"


class TierCode(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class TierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ViewerStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    TIMED_OUT = "TIMED_OUT"
    BANNED = "BANNED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PerkStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class ModeratorStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class ModerationScope(str, Enum):
    TIMEOUT = "TIMEOUT"
    BAN = "BAN"


class ModerationActionKind(str, Enum):
    TIMEOUT = "TIMEOUT"
    BAN = "BAN"


class ModerationActionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"
    EXPIRED = "EXPIRED"


class PolicyCode(str, Enum):
    COPYRIGHT = "COPYRIGHT"
    HATE_SPEECH = "HATE_SPEECH"
    NUDITY = "NUDITY"
    HARASSMENT = "HARASSMENT"
    SPAM = "SPAM"


class StrikeSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class StrikeStatus(str, Enum):
    ISSUED = "ISSUED"
    UNDER_APPEAL = "UNDER_APPEAL"
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"
    EXPIRED = "EXPIRED"


class DealCategory(str, Enum):
    GAMING_HARDWARE = "GAMING_HARDWARE"
    ENERGY_DRINK = "ENERGY_DRINK"
    VPN = "VPN"
    GAME_PUBLISHER = "GAME_PUBLISHER"
    OTHER = "OTHER"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    BREACHED = "BREACHED"
    CANCELLED = "CANCELLED"


class DeliverableKind(str, Enum):
    AD_READ = "AD_READ"
    SPONSORED_SEGMENT = "SPONSORED_SEGMENT"
    LOGO_PLACEMENT = "LOGO_PLACEMENT"
    PRODUCT_PLACEMENT = "PRODUCT_PLACEMENT"


class PerformanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PERFORMED = "PERFORMED"
    VERIFIED = "VERIFIED"
    MISSED = "MISSED"
    DISPUTED = "DISPUTED"


class DisclosureStatus(str, Enum):
    PENDING = "PENDING"
    DISCLOSED_ON_TIME = "DISCLOSED_ON_TIME"
    DISCLOSED_LATE = "DISCLOSED_LATE"
    MISSING = "MISSING"


class StreamStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class GrantPlatform(str, Enum):
    TWITCH = "TWITCH"
    YOUTUBE = "YOUTUBE"
    KICK = "KICK"


class GrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Channel(TypedDict):
    id: str
    handle: str
    display_name: str
    home_platform: str
    payout_schedule: str
    payout_threshold_cents: int
    monetization_posture: str
    balance_pending_cents: int
    balance_payable_cents: int
    lifetime_paid_cents: int
    trust_score_bp: int
    projected_strike_weight: float
    consistency_score_bps: int
    active_strike_count: int
    tax_form_current_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxForm(TypedDict):
    id: str
    channel_id: str
    form_type: str
    legal_name: str
    tax_id_last4: str
    tax_status: str
    submitted_at: str
    verified_at: Optional[str]
    rejection_reason: Optional[str]
    expires_on: Optional[str]
    prior_form_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RevenueEvent(TypedDict):
    # Append-only ledger entry (PRD resource-identity section): id + created_at
    # only — NO updated_at, NO version.
    id: str
    channel_id: str
    kind: str
    gross_cents: int
    platform_fee_bps: int
    occurred_at: str
    recognition_status: str
    settlement_month: str
    reverses_event_id: Optional[str]
    net_cents: int
    withholding_cents: int
    created_at: str


class Payout(TypedDict):
    id: str
    channel_id: str
    payout_status: str
    amount_cents: int
    withholding_cents: int
    fee_cents: int
    net_transfer_cents: int
    settled_event_count: int
    retry_count: int
    failure_reason: Optional[str]
    hold_reason: str
    scheduled_for: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionTier(TypedDict):
    id: str
    channel_id: str
    tier_code: str
    monthly_price_cents: int
    revenue_share_bps: int
    perk_inventory_total: int
    perk_inventory_remaining: int
    tier_status: str
    created_at: str
    updated_at: str
    version: int


class Viewer(TypedDict):
    id: str
    channel_id: str
    handle: str
    standing: str
    lifetime_spend_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    channel_id: str
    viewer_id: str
    tier_id: str
    sub_status: str
    started_at: str
    current_period_end: str
    cycles_paid: int
    created_at: str
    updated_at: str
    version: int


class PerkGrant(TypedDict):
    id: str
    subscription_id: str
    perk_kind: str
    perk_status: str
    due_at: str
    failure_count: int
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Moderator(TypedDict):
    id: str
    channel_id: str
    moderator_handle: str
    scopes: List[str]
    moderator_status: str
    actions_issued_count: int
    created_at: str
    updated_at: str
    version: int


class ModerationAction(TypedDict):
    id: str
    channel_id: str
    viewer_id: str
    moderator_id: Optional[str]
    action_kind: str
    duration_minutes: Optional[int]
    reason: str
    action_status: str
    issued_at: str
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContentStrike(TypedDict):
    id: str
    channel_id: str
    policy_code: str
    severity: str
    evidence_ref: str
    strike_status: str
    issued_at: str
    expires_at: str
    appeal_deadline: str
    appeal_round: int
    issued_by_user_id: str
    resolved_by_user_id: Optional[str]
    upheld_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SponsorshipDeal(TypedDict):
    id: str
    channel_id: str
    sponsor_ref: str
    title: str
    category: str
    total_value_cents: int
    flight_start: str
    flight_end: str
    required_deliverable_count: int
    deal_status: str
    miss_count: int
    verified_deliverable_count: int
    disclosure_compliant: bool
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    deal_id: str
    stream_id: Optional[str]
    kind: str
    due_at: str
    performance_status: str
    disclosure_status: str
    performed_at: Optional[str]
    disclosure_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StreamSession(TypedDict):
    id: str
    channel_id: str
    title: str
    scheduled_start: str
    scheduled_end: str
    simulcast: bool
    stream_status: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    peak_viewers: Optional[int]
    avg_viewers: Optional[int]
    punctuality_minutes_late: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SimulcastGrant(TypedDict):
    id: str
    channel_id: str
    platform: str
    window_start: str
    window_end: str
    exclusive: bool
    grant_status: str
    created_at: str
    updated_at: str
    version: int
