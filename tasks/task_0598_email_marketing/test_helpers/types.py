"""Domain types for the Email Marketing Automation API: entity TypedDicts, status enums, roles."""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ───────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CAMPAIGN_AUTHOR = "CampaignAuthor"
    COMPLIANCE_APPROVER = "ComplianceApprover"
    ANONYMOUS = "Anonymous"


class AccountUserRole(str, Enum):
    """AccountUser.user_role — decides which X-User-Role headers the operator may claim."""
    CAMPAIGN_AUTHOR = "CAMPAIGN_AUTHOR"
    COMPLIANCE_APPROVER = "COMPLIANCE_APPROVER"
    DUAL = "DUAL"


# ─── Status enums ───────────────────────────────────────────────────────────

class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SuspensionReason(str, Enum):
    HIGH_HARD_BOUNCE_RATE = "HIGH_HARD_BOUNCE_RATE"


class PlanTier(str, Enum):
    FREE = "FREE"
    ESSENTIALS = "ESSENTIALS"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ConsentState(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    CLEANED = "CLEANED"
    ARCHIVED = "ARCHIVED"


class ConsentSource(str, Enum):
    SIGNUP_FORM = "SIGNUP_FORM"
    IMPORT = "IMPORT"
    API = "API"
    MANUAL = "MANUAL"


class EngagementState(str, Enum):
    NEW = "NEW"
    ENGAGED = "ENGAGED"
    DORMANT = "DORMANT"
    LAPSED = "LAPSED"


class ImportJobStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    SENDING = "SENDING"
    SENT = "SENT"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    QUEUED = "QUEUED"
    DELIVERED = "DELIVERED"
    SOFT_BOUNCED = "SOFT_BOUNCED"
    HARD_BOUNCED = "HARD_BOUNCED"
    SUPPRESSED = "SUPPRESSED"
    COMPLAINED = "COMPLAINED"
    CANCELLED = "CANCELLED"


class EngagementStatus(str, Enum):
    NOT_OPENED = "NOT_OPENED"
    OPENED = "OPENED"
    CLICKED = "CLICKED"


class VariantLabel(str, Enum):
    A = "A"
    B = "B"


class SuppressionReason(str, Enum):
    UNSUBSCRIBE = "UNSUBSCRIBE"
    HARD_BOUNCE = "HARD_BOUNCE"
    COMPLAINT = "COMPLAINT"


class JourneyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class JourneyTrigger(str, Enum):
    SUBSCRIBE_CONFIRMED = "SUBSCRIBE_CONFIRMED"
    CAMPAIGN_CLICK = "CAMPAIGN_CLICK"


class JourneyStepKind(str, Enum):
    WAIT = "WAIT"
    EMAIL = "EMAIL"
    CONDITION = "CONDITION"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SUPPRESSED = "SUPPRESSED"


class BillingCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EventKind(str, Enum):
    DELIVERED = "DELIVERED"
    SOFT_BOUNCE = "SOFT_BOUNCE"
    HARD_BOUNCE = "HARD_BOUNCE"
    COMPLAINT = "COMPLAINT"
    OPEN = "OPEN"
    CLICK = "CLICK"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"


# ─── Entity shapes (PRD §2.4: mutable resources carry updated_at + version) ──

class Account(TypedDict):
    id: str
    name: str
    plan_tier: str
    status: str
    suspension_reason: Optional[str]
    hourly_send_capacity: int
    granted_send_credits: int
    send_credit_balance: int
    reserved_send_credits: int
    consumed_send_credits: int
    billable_contact_count: int
    sender_reputation_score: int
    created_at: str
    updated_at: str
    version: int


class AccountUser(TypedDict):
    id: str
    account_id: str
    email: str
    user_role: str
    created_at: str
    updated_at: str
    version: int


class Audience(TypedDict):
    id: str
    account_id: str
    name: str
    double_optin_required: bool
    default_from_email: str
    subscriber_count: int
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict):
    id: str
    audience_id: str
    email: str
    first_name: Optional[str]
    consent_source: str
    consent_state: str
    engagement_state: str
    confirmation_token: Optional[str]
    unsubscribe_token: str
    consent_confirmed_at: Optional[str]
    unsubscribed_at: Optional[str]
    delivered_send_count: int
    opened_send_count: int
    clicked_send_count: int
    last_opened_at: Optional[str]
    engagement_score: int
    engagement_score_90d: int
    created_at: str
    updated_at: str
    version: int


class ImportJob(TypedDict):
    id: str
    audience_id: str
    rows: list
    status: str
    row_count: int
    accepted_count: int
    rejected_count: int
    duplicate_count: int
    suppressed_count: int
    created_subscriber_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class Segment(TypedDict):
    id: str
    audience_id: str
    name: str
    consent_states: List[str]
    min_engagement_score: int
    max_days_since_open: Optional[int]
    member_count: int
    created_at: str
    updated_at: str
    version: int


class Template(TypedDict):
    id: str
    account_id: str
    name: str
    subject: str
    html_body: str
    has_unsubscribe_link: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    account_id: str
    audience_id: str
    segment_id: Optional[str]
    template_id: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    name: str
    status: str
    ab_test_enabled: bool
    variant_split_pct: int
    variant_b_subject: Optional[str]
    pinned_subject: Optional[str]
    pinned_html_body: Optional[str]
    pinned_template_version: Optional[int]
    review_note: Optional[str]
    scheduled_at: Optional[str]
    send_window_minutes: Optional[int]
    recipient_snapshot_ids: List[str]
    recipient_count: int
    reserved_credit_count: int
    send_charge_cents: int
    winning_variant: Optional[str]
    winner_selected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Send(TypedDict):
    id: str
    campaign_id: Optional[str]
    journey_id: Optional[str]
    subscriber_id: str
    variant_label: Optional[str]
    delivery_status: str
    engagement_status: str
    soft_bounce_count: int
    open_count: int
    click_count: int
    delivered_at: Optional[str]
    first_opened_at: Optional[str]
    last_clicked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SuppressionEntry(TypedDict):
    """Immutable (PRD §2.4): carries only id and created_at — no updated_at, no version."""
    id: str
    account_id: str
    email: str
    reason: str
    created_at: str


class Journey(TypedDict):
    id: str
    account_id: str
    audience_id: str
    name: str
    trigger_event: str
    steps: list
    status: str
    active_enrollment_count: int
    entered_count: int
    created_at: str
    updated_at: str
    version: int


class JourneyEnrollment(TypedDict):
    id: str
    journey_id: str
    subscriber_id: str
    status: str
    current_step_index: int
    next_action_at: str
    enrolled_at: str
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict):
    id: str
    account_id: str
    period_start: str
    period_end: str
    status: str
    peak_contact_count: int
    tier_applied: Optional[str]
    base_fee_cents: int
    overage_cents: int
    total_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
