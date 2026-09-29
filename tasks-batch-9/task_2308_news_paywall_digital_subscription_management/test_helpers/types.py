"""Domain types for the News Paywall & Digital Subscription Management API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them. Payment attempts and reader events are append-only records and
therefore carry only ``id`` and ``created_at`` — no ``updated_at``, no
``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1 — "Five roles exist and their spelling is exact")
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    READER = "Reader"
    GROUP_ADMIN = "GroupAdmin"
    SUBSCRIPTION_OPS_AGENT = "SubscriptionOpsAgent"
    REVENUE_MANAGER = "RevenueManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --------------------------------------------------------------------------
# Offer plan dimensions
# --------------------------------------------------------------------------


class OfferPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class PriceChangeState(str, Enum):
    NONE = "NONE"
    SCHEDULED = "SCHEDULED"
    NOTICE_SENT = "NOTICE_SENT"
    APPLIED = "APPLIED"


class BundleType(str, Enum):
    DIGITAL_ONLY = "DIGITAL_ONLY"
    PRINT_DIGITAL = "PRINT_DIGITAL"
    INSTITUTIONAL_SEAT = "INSTITUTIONAL_SEAT"


class GrandfatherPolicy(str, Enum):
    NONE = "NONE"
    TENURE_12_CYCLES = "TENURE_12_CYCLES"
    ALL_EXISTING = "ALL_EXISTING"


class PriceSource(str, Enum):
    INTRO = "INTRO"
    STEP_UP = "STEP_UP"
    STANDARD = "STANDARD"
    GRANDFATHERED = "GRANDFATHERED"
    PRORATED_SEGMENTS = "PRORATED_SEGMENTS"


# --------------------------------------------------------------------------
# Paywall rule / article / decision vocabulary
# --------------------------------------------------------------------------


class PaywallRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ContentType(str, Enum):
    NEWS = "NEWS"
    OPINION = "OPINION"
    INVESTIGATION = "INVESTIGATION"
    LIVE_BLOG = "LIVE_BLOG"
    ANY = "ANY"


class PropensityBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    ANY = "ANY"


class PaywallAction(str, Enum):
    ALLOW_FREE = "ALLOW_FREE"
    METER = "METER"
    REGISTRATION_WALL = "REGISTRATION_WALL"
    HARD_PAYWALL = "HARD_PAYWALL"


class AccessClass(str, Enum):
    OPEN = "OPEN"
    METERED = "METERED"
    PREMIUM = "PREMIUM"


class AccessDecision(str, Enum):
    GRANTED_FREE = "GRANTED_FREE"
    GRANTED_ENTITLED = "GRANTED_ENTITLED"
    GRANTED_METERED = "GRANTED_METERED"
    BLOCKED_REGISTRATION = "BLOCKED_REGISTRATION"
    BLOCKED_METER = "BLOCKED_METER"
    BLOCKED_PAYWALL = "BLOCKED_PAYWALL"


class ReaderEventType(str, Enum):
    ARTICLE_VIEW_GRANTED = "ARTICLE_VIEW_GRANTED"
    ARTICLE_VIEW_BLOCKED = "ARTICLE_VIEW_BLOCKED"
    NEWSLETTER_OPEN = "NEWSLETTER_OPEN"
    APP_OPEN = "APP_OPEN"
    COMMENT_POST = "COMMENT_POST"
    INTERVENTION_EDITORIAL = "INTERVENTION_EDITORIAL"
    INTERVENTION_PRODUCT = "INTERVENTION_PRODUCT"
    PRICE_INCREASE_NOTICE = "PRICE_INCREASE_NOTICE"


# --------------------------------------------------------------------------
# Reader dimensions
# --------------------------------------------------------------------------


class ChurnRiskBand(str, Enum):
    SEVERE = "SEVERE"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EntitlementSource(str, Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    SEAT = "SEAT"
    NONE = "NONE"


class CardStatus(str, Enum):
    MISSING = "MISSING"
    EXPIRED = "EXPIRED"
    CURRENT = "CURRENT"


class CardUpdaterStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    UPDATED = "UPDATED"
    UNAVAILABLE = "UNAVAILABLE"


# --------------------------------------------------------------------------
# Subscription's three independent dimensions (PRD §2.10)
# --------------------------------------------------------------------------


class LifecycleStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCEL_SCHEDULED = "CANCEL_SCHEDULED"
    CANCELLED = "CANCELLED"
    CANCELLED_NONPAY = "CANCELLED_NONPAY"


class DunningStatus(str, Enum):
    CURRENT = "CURRENT"
    RETRYING = "RETRYING"
    RECOVERED = "RECOVERED"
    FAILED_FINAL = "FAILED_FINAL"


class PrintFulfillmentStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    INTERRUPTED = "INTERRUPTED"
    STOPPED_AT_CYCLE_END = "STOPPED_AT_CYCLE_END"
    STOPPED = "STOPPED"


# --------------------------------------------------------------------------
# Invoicing / dunning
# --------------------------------------------------------------------------


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    WRITTEN_OFF = "WRITTEN_OFF"
    VOID = "VOID"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    SOFT_DECLINE = "SOFT_DECLINE"
    HARD_DECLINE = "HARD_DECLINE"


# --------------------------------------------------------------------------
# Cancellation flow / save offers
# --------------------------------------------------------------------------


class CancellationRequestStatus(str, Enum):
    INITIATED = "INITIATED"
    SAVE_OFFER_PRESENTED = "SAVE_OFFER_PRESENTED"
    SAVE_OFFER_ACCEPTED = "SAVE_OFFER_ACCEPTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class CancellationReasonCode(str, Enum):
    PRICE = "PRICE"
    CONTENT = "CONTENT"
    TECHNICAL = "TECHNICAL"
    LIFE_CHANGE = "LIFE_CHANGE"
    OTHER = "OTHER"


class SaveOfferTier(str, Enum):
    RICH = "RICH"
    STANDARD = "STANDARD"
    MINIMAL = "MINIMAL"


class SaveOfferType(str, Enum):
    RETENTION_DISCOUNT = "RETENTION_DISCOUNT"
    PAUSE = "PAUSE"
    DOWNGRADE = "DOWNGRADE"


class SaveOfferStatus(str, Enum):
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class SaveOfferDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


# --------------------------------------------------------------------------
# Holds
# --------------------------------------------------------------------------


class HoldType(str, Enum):
    PAUSE_BILLING = "PAUSE_BILLING"
    VACATION_DELIVERY = "VACATION_DELIVERY"
    DELIVERY_INTERRUPTION = "DELIVERY_INTERRUPTION"


class HoldStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


# --------------------------------------------------------------------------
# Institutional access
# --------------------------------------------------------------------------


class GroupAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SeatStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    RECLAIMED = "RECLAIMED"
    EXPIRED = "EXPIRED"


class WeekdayCode(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class BillingRunScope(str, Enum):
    FULL = "FULL"
    HOLDS_ONLY = "HOLDS_ONLY"
    EXPIRY_ONLY = "EXPIRY_ONLY"
    BILLING_ONLY = "BILLING_ONLY"
    DUNNING_ONLY = "DUNNING_ONLY"
    ENGAGEMENT_ONLY = "ENGAGEMENT_ONLY"


# --------------------------------------------------------------------------
# Entity shapes — full common property set (PRD §2.5)
# --------------------------------------------------------------------------


class OfferPlan(TypedDict):
    id: str
    name: str
    bundle_type: str
    status: str
    intro_price_cents: int
    intro_cycles: int
    step_up_schedule: List[dict]
    standard_from_cycle: int
    standard_price_cents: int
    cycle_days: int
    print_component_cents: int
    print_delivery_days: List[str]
    print_deliveries_per_cycle: int
    per_seat_price_cents: int
    price_change_state: str
    pending_price_cents: Optional[int]
    pending_effective_on: Optional[str]
    notice_sent_on: Optional[str]
    notice_sent_by_user_id: Optional[str]
    grandfather_policy: str
    active_subscription_count: int
    created_at: str
    updated_at: str
    version: int


class PaywallRule(TypedDict):
    id: str
    name: str
    status: str
    content_type_match: str
    section_match: str
    propensity_band_match: str
    action: str
    meter_allowance_override: Optional[int]
    priority: int
    specificity_score: int
    created_at: str
    updated_at: str
    version: int


class Article(TypedDict):
    id: str
    headline: str
    content_type: str
    section: str
    access_class: str
    published_at: str
    created_at: str
    updated_at: str
    version: int


class Reader(TypedDict):
    id: str
    email: Optional[str]
    is_registered: bool
    propensity_band: str
    engagement_score: float
    churn_risk_band: str
    metered_article_ids: List[str]
    metered_distinct_article_count: int
    meter_period_started_on: str
    entitlement_source: str
    tenure_days: int
    intervention_count_in_period: int
    card_last4: Optional[str]
    card_exp_month: Optional[int]
    card_exp_year: Optional[int]
    card_status: str
    card_updater_registered: bool
    card_updater_status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    reader_id: str
    offer_plan_id: str
    group_account_id: Optional[str]
    lifecycle_status: str
    dunning_status: str
    print_fulfillment_status: str
    cycle_index: int
    cycle_start_on: str
    paid_through_on: Optional[str]
    access_until: Optional[str]
    next_cycle_price_cents: int
    locked_price_cents: Optional[int]
    grandfathered_until_cycle: Optional[int]
    retention_discount_pct: float
    retention_discount_cycles_remaining: int
    pending_credit_cents: int
    lifetime_credit_cents: int
    dunning_first_failed_on: Optional[str]
    next_retry_on: Optional[str]
    payment_attempt_count: int
    max_payment_attempts: int
    vacation_days_used_365: int
    tenure_cycles: int
    cancel_effective_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    subscription_id: str
    cycle_index: int
    status: str
    price_source: str
    base_line_cents: int
    seat_line_cents: int
    discount_line_cents: int
    credit_line_cents: int
    total_cents: int
    due_on: str
    paid_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CancellationRequest(TypedDict):
    id: str
    subscription_id: str
    status: str
    reason_code: str
    save_offer_count: int
    projected_engagement_score: float
    eligible_save_offer_tier: str
    confirmed_on: Optional[str]
    effective_on: Optional[str]
    retained: bool
    created_at: str
    updated_at: str
    version: int


class SaveOffer(TypedDict):
    id: str
    cancellation_request_id: str
    offer_type: str
    discount_pct: float
    duration_cycles: int
    pause_days: int
    status: str
    presented_on: str
    decided_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hold(TypedDict):
    id: str
    subscription_id: str
    hold_type: str
    start_date: str
    end_date: str
    status: str
    delivery_days_credited: int
    credit_cents: int
    credit_applied: bool
    credit_applied_cycle_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


class GroupAccount(TypedDict):
    id: str
    name: str
    admin_email: str
    allowed_email_domain: str
    seat_capacity: int
    offer_plan_id: str
    status: str
    seats_assigned_count: int
    seats_available_count: int
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict):
    id: str
    group_account_id: str
    reader_id: str
    status: str
    starts_on: str
    ends_on: Optional[str]
    invited_on: str
    invite_expires_on: str
    claimed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only records — only id + created_at (PRD §2.5)
# --------------------------------------------------------------------------


class PaymentAttempt(TypedDict):
    id: str
    invoice_id: str
    attempt_no: int
    outcome: str
    amount_cents: int
    decline_code: Optional[str]
    is_final: bool
    attempted_on: str
    card_last4_snapshot: Optional[str]
    created_at: str
    # No updated_at and no version: payment attempts are append-only.


class ReaderEvent(TypedDict):
    id: str
    reader_id: str
    article_id: Optional[str]
    applied_rule_id: Optional[str]
    event_type: str
    decision: Optional[str]
    meter_index: Optional[int]
    effective_allowance: Optional[int]
    weight: int
    occurred_at: str
    created_at: str
    # No updated_at and no version: reader events are append-only.


class BillingRunReport(TypedDict):
    run_id: str
    scope: str
    holds_activated: List[str]
    holds_completed: List[str]
    subscriptions_paused: List[str]
    subscriptions_resumed: List[str]
    cancellations_completed: List[str]
    seats_expired: List[str]
    invoices_created: List[str]
    subscriptions_cancelled_nonpay: List[str]
    cards_updated: List[str]
    readers_rescored: List[str]


BILLING_RUN_ARRAYS = (
    "holds_activated",
    "holds_completed",
    "subscriptions_paused",
    "subscriptions_resumed",
    "cancellations_completed",
    "seats_expired",
    "invoices_created",
    "subscriptions_cancelled_nonpay",
    "cards_updated",
    "readers_rescored",
)
