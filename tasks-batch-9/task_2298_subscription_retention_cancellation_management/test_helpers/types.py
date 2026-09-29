"""Domain types for the Subscription Retention & Cancellation Management API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.  Two resources are append-only records of something that already
happened and therefore carry only ``id`` and ``created_at`` (PRD §2.4):
``DunningAttempt`` and ``RetentionCohortSnapshot``.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    SUBSCRIBER = "Subscriber"
    RETENTION_SPECIALIST = "RetentionSpecialist"
    BILLING_OPERATOR = "BillingOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AcquisitionChannel(str, Enum):
    PAID_SOCIAL = "PAID_SOCIAL"
    SEARCH = "SEARCH"
    AFFILIATE = "AFFILIATE"
    ORGANIC = "ORGANIC"
    REFERRAL = "REFERRAL"


class TenureBucket(str, Enum):
    M0_1 = "M0_1"
    M2_3 = "M2_3"
    M4_6 = "M4_6"
    M7_12 = "M7_12"
    M13_PLUS = "M13_PLUS"


class ChurnType(str, Enum):
    NONE = "NONE"
    VOLUNTARY = "VOLUNTARY"
    INVOLUNTARY = "INVOLUNTARY"


class LifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    PENDING_CANCEL = "PENDING_CANCEL"
    CANCELLED = "CANCELLED"


class BillingState(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    GRACE = "GRACE"
    DELINQUENT = "DELINQUENT"


class PaymentMethodStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPLACED = "REPLACED"
    EXPIRED = "EXPIRED"


class UpdaterStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    UPDATED = "UPDATED"
    UNAVAILABLE = "UNAVAILABLE"


class CardNetwork(str, Enum):
    VISA = "VISA"
    MASTERCARD = "MASTERCARD"
    AMEX = "AMEX"
    DISCOVER = "DISCOVER"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    FAILED = "FAILED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class DunningOutcome(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    SOFT_DECLINE = "SOFT_DECLINE"
    HARD_DECLINE = "HARD_DECLINE"


class DeclineCode(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    EXPIRED_CARD = "EXPIRED_CARD"
    DO_NOT_HONOR = "DO_NOT_HONOR"
    LOST_STOLEN = "LOST_STOLEN"


class CancellationSessionState(str, Enum):
    STARTED = "STARTED"
    REASON_CAPTURED = "REASON_CAPTURED"
    OFFERS_PRESENTED = "OFFERS_PRESENTED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    COMPLETED_CANCELLED = "COMPLETED_CANCELLED"
    ABANDONED = "ABANDONED"


class ReasonCode(str, Enum):
    PRICE = "PRICE"
    PRODUCT_FIT = "PRODUCT_FIT"
    TOO_MUCH_PRODUCT = "TOO_MUCH_PRODUCT"
    SHIPPING_ISSUES = "SHIPPING_ISSUES"
    FINANCIAL_HARDSHIP = "FINANCIAL_HARDSHIP"
    OTHER = "OTHER"


class EntryChannel(str, Enum):
    WEB_SELF_SERVE = "WEB_SELF_SERVE"
    APP_SELF_SERVE = "APP_SELF_SERVE"
    AGENT_ASSISTED = "AGENT_ASSISTED"


class OfferType(str, Enum):
    PAUSE = "PAUSE"
    SKIP = "SKIP"
    DISCOUNT = "DISCOUNT"
    PLAN_DOWNGRADE = "PLAN_DOWNGRADE"


class SaveOfferTemplateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class GrantState(str, Enum):
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class MarginExceptionState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ModType(str, Enum):
    FREQUENCY_CHANGE = "FREQUENCY_CHANGE"
    ADDON_ADD = "ADDON_ADD"
    ADDON_REMOVE = "ADDON_REMOVE"
    SKIP_SHIPMENT = "SKIP_SHIPMENT"
    PLAN_DOWNGRADE = "PLAN_DOWNGRADE"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    DISCOUNT_APPLY = "DISCOUNT_APPLY"


class ModificationState(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class NoticeType(str, Enum):
    NEGATIVE_OPTION_DISCLOSURE = "NEGATIVE_OPTION_DISCLOSURE"
    RENEWAL_REMINDER = "RENEWAL_REMINDER"
    PRICE_CHANGE = "PRICE_CHANGE"
    CANCELLATION_CONFIRMATION = "CANCELLATION_CONFIRMATION"


class NoticeState(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    MISSED = "MISSED"


class NoticeChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"


class CampaignState(str, Enum):
    DRAFT = "DRAFT"
    LAUNCHED = "LAUNCHED"
    CLOSED = "CLOSED"


class TargetState(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SUPPRESSED = "SUPPRESSED"
    SENT = "SENT"
    EXPIRED = "EXPIRED"
    CONVERTED = "CONVERTED"


class SuppressionReason(str, Enum):
    NONE = "NONE"
    RECENT_SAVE_OFFER = "RECENT_SAVE_OFFER"
    ACTIVE_SUBSCRIPTION = "ACTIVE_SUBSCRIPTION"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"
    INVOLUNTARY_UNRESOLVED = "INVOLUNTARY_UNRESOLVED"
    CONTACT_CAP = "CONTACT_CAP"


class LtvVariant(str, Enum):
    REALIZED = "REALIZED"
    PROJECTED = "PROJECTED"


class UpdaterOutcome(str, Enum):
    UPDATED = "UPDATED"
    UNAVAILABLE = "UNAVAILABLE"


class MarginExceptionDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (PRD §2.4)
# ---------------------------------------------------------------------------

class Plan(TypedDict):
    id: str
    code: str
    name: str
    monthly_price_cents: int
    unit_cogs_cents: int
    shipments_per_cycle: int
    shipments_per_term: int
    allowed_frequency_weeks: List[int]
    margin_floor_pct: float
    is_negative_option: bool
    renewal_reminder_days_before: int
    max_pause_cycles: int
    addon_catalog: List[Dict[str, Any]]
    downgrade_target_plan_id: Optional[str]
    status: str
    active_subscription_count: int
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict):
    id: str
    email: str
    acquisition_channel: str
    do_not_contact: bool
    first_subscribed_at: Optional[str]
    lapsed_at: Optional[str]
    won_back_at: Optional[str]
    tenure_days: int
    tenure_bucket: str
    churn_type: str
    realized_ltv_cents: int
    projected_ltv_cents: int
    save_offer_grants_365d_count: int
    winback_suppressed_until: Optional[str]
    last_contacted_at: Optional[str]
    cohort_month: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    subscriber_id: str
    plan_id: str
    payment_method_id: str
    lifecycle_state: str
    billing_state: str
    frequency_weeks: int
    addons: List[Dict[str, Any]]
    active_discount_pct: float
    discount_remaining_cycles: int
    baseline_price_cents: int
    committed_price_cents: int
    next_renewal_at: str
    next_ship_at: str
    paused_until: Optional[str]
    pause_cycles_used: int
    term_shipments_delivered: int
    term_shipments_skipped: int
    term_shipments_remaining: int
    cancel_effective_at: Optional[str]
    first_failed_at: Optional[str]
    grace_end_at: Optional[str]
    consecutive_failed_attempts: int
    disclosure_acknowledged: bool
    created_at: str
    updated_at: str
    version: int


class PaymentMethod(TypedDict):
    id: str
    subscriber_id: str
    card_last4: str
    exp_month: int
    exp_year: int
    network: str
    status: str
    updater_status: str
    updater_requested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    subscription_id: str
    payment_method_id: str
    cycle_index: int
    amount_cents: int
    cogs_cents: int
    line_items: List[Dict[str, Any]]
    status: str
    due_at: str
    paid_at: Optional[str]
    attempt_count: int
    proration_factor: float
    is_renewal: bool
    created_at: str
    updated_at: str
    version: int


class CancellationSession(TypedDict):
    id: str
    subscription_id: str
    state: str
    reason_code: Optional[str]
    reason_detail: Optional[str]
    step_count: int
    offers_presented_count: int
    entry_channel: str
    started_at: str
    completed_at: Optional[str]
    presented_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SaveOfferTemplate(TypedDict):
    id: str
    code: str
    name: str
    offer_type: str
    discount_pct: float
    discount_cycles: int
    pause_cycles: int
    skip_count: int
    min_tenure_days: int
    eligible_reason_codes: List[str]
    max_per_subscriber_per_365d: int
    priority_rank: int
    expires_after_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SaveOfferGrant(TypedDict):
    id: str
    cancellation_session_id: str
    save_offer_template_id: str
    subscription_id: str
    state: str
    per_cycle_margin_pct: float
    blended_term_margin_pct: float
    margin_exception_required: bool
    margin_exception_state: str
    presented_by_user_id: str
    decided_by_user_id: Optional[str]
    expires_at: str
    accepted_at: Optional[str]
    retention_value_cents: int
    created_at: str
    updated_at: str
    version: int


class SubscriptionModification(TypedDict):
    id: str
    subscription_id: str
    save_offer_grant_id: Optional[str]
    reverses_modification_id: Optional[str]
    target_plan_id: Optional[str]
    mod_type: str
    state: str
    frequency_weeks: Optional[int]
    addon_code: Optional[str]
    addon_qty: Optional[int]
    skip_ship_at: Optional[str]
    pause_start_at: Optional[str]
    pause_end_at: Optional[str]
    effective_at: str
    delta_price_cents: int
    prior_snapshot: Optional[Dict[str, Any]]
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceNotice(TypedDict):
    id: str
    subscription_id: str
    notice_type: str
    state: str
    scheduled_for: str
    sent_at: Optional[str]
    channel: str
    renewal_cycle_index: int
    body_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WinBackCampaign(TypedDict):
    id: str
    code: str
    name: str
    target_channels: List[str]
    target_reason_codes: List[str]
    min_days_since_lapse: int
    max_days_since_lapse: int
    offer_discount_pct: float
    send_window_days: int
    suppression_days: int
    state: str
    targeted_count: int
    sent_count: int
    converted_count: int
    created_at: str
    updated_at: str
    version: int


class WinBackTarget(TypedDict):
    id: str
    winback_campaign_id: str
    subscriber_id: str
    state: str
    suppression_reason: str
    priority_score: float
    projected_ltv_cents: int
    sent_at: Optional[str]
    expires_at: Optional[str]
    converted_at: Optional[str]
    days_since_lapse_at_target: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only resources: id + created_at ONLY (PRD §2.4)
# ---------------------------------------------------------------------------

class DunningAttempt(TypedDict):
    id: str
    invoice_id: str
    previous_attempt_id: Optional[str]
    attempt_number: int
    scheduled_at: str
    attempted_at: Optional[str]
    outcome: str
    decline_code: Optional[str]
    backoff_days_applied: int
    grace_clamped: bool
    is_final: bool
    created_at: str


class RetentionCohortSnapshot(TypedDict):
    id: str
    cohort_month: str
    acquisition_channel: Optional[str]
    plan_code: Optional[str]
    tenure_bucket: Optional[str]
    ltv_variant: str
    member_count: int
    retained_count: int
    churned_voluntary_count: int
    churned_involuntary_count: int
    retention_rate: float
    mean_ltv_cents: int
    computed_at: str
    created_at: str
