"""Domain types: entity TypedDicts, status enums, role enum.

All field names are PRD-exact. Entities whose ledger/config nature makes them
append-only (BillingEvent) carry only ``billing_event_id`` + ``created_at``
from the common set — no ``updated_at``, no ``version`` (PRD section 2.5).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class PlanTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ProfileStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class SubscriptionStatus(str, Enum):
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class BillingState(str, Enum):
    CURRENT = "CURRENT"
    DUNNING = "DUNNING"
    RECOVERED = "RECOVERED"


class CancelReason(str, Enum):
    USER_REQUESTED = "USER_REQUESTED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PRICE_REFUSAL = "PRICE_REFUSAL"
    WINBACK_EXPIRED = "WINBACK_EXPIRED"
    ADMIN = "ADMIN"


class BillingEventType(str, Enum):
    TRIAL_START = "TRIAL_START"
    CHARGE = "CHARGE"
    CHARGE_FAILED = "CHARGE_FAILED"
    REFUND = "REFUND"
    PRORATION_CREDIT = "PRORATION_CREDIT"
    PRICE_CHANGE_APPLIED = "PRICE_CHANGE_APPLIED"
    RECOVERY = "RECOVERY"


class OfferType(str, Enum):
    PAUSE_1M = "PAUSE_1M"
    PAUSE_3M = "PAUSE_3M"
    DOWNGRADE = "DOWNGRADE"
    DISCOUNT_50_3M = "DISCOUNT_50_3M"


class OfferStatus(str, Enum):
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class NoticeStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    EFFECTIVE = "EFFECTIVE"
    CANCELLED = "CANCELLED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ReportStatus(str, Enum):
    EXPECTED = "EXPECTED"
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    DISCREPANCY = "DISCREPANCY"
    WRITE_OFF = "WRITE_OFF"


class Channel(str, Enum):
    ORGANIC = "ORGANIC"
    SEARCH = "SEARCH"
    SOCIAL = "SOCIAL"
    AD = "AD"
    EMAIL = "EMAIL"
    REFERRAL = "REFERRAL"


class UserRole(str, Enum):
    SUBSCRIBER = "Subscriber"
    SUPPORT_AGENT = "SupportAgent"
    PARTNER_BILLING_OPS = "PartnerBillingOps"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Entity TypedDicts — full common set (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Plan(TypedDict, total=False):
    plan_id: str
    plan_code: str
    display_name: str
    tier: str
    monthly_price_cents: int
    trial_days: int
    max_profiles: int
    max_households: int
    is_archived: bool
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    account_id: str
    email: str
    full_name: str
    country_code: str
    account_status: str
    created_via_partner_id: Optional[str]
    outstanding_balance_cents: int
    active_subscription_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Profile(TypedDict, total=False):
    profile_id: str
    account_id: str
    display_name: str
    is_kids: bool
    household_id: str
    profile_status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    subscription_id: str
    account_id: str
    plan_id: str
    subscription_status: str
    billing_state: str
    cancel_reason: Optional[str]
    period_start_utc: str
    period_end_utc: str
    trial_end_utc: Optional[str]
    paused_until_utc: Optional[str]
    pending_plan_id: Optional[str]
    grandfathered_price_cents: Optional[int]
    save_offer_id: Optional[str]
    signup_attribution_id: Optional[str]
    dunning_attempt_count: int
    price_change_notice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SaveOffer(TypedDict, total=False):
    save_offer_id: str
    account_id: str
    subscription_id: str
    offer_type: str
    offer_status: str
    discount_pct: int
    discount_duration_months: int
    target_plan_id: Optional[str]
    presented_at_utc: str
    expires_at_utc: str
    created_at: str
    updated_at: str
    version: int


class PriceChangeNotice(TypedDict, total=False):
    price_change_notice_id: str
    plan_id: str
    old_price_cents: int
    new_price_cents: int
    announced_at_utc: str
    effective_at_utc: str
    notice_status: str
    grandfather_period_months: int
    created_at: str
    updated_at: str
    version: int


class WinbackCampaign(TypedDict, total=False):
    winback_campaign_id: str
    campaign_code: str
    discount_pct: int
    duration_months: int
    min_days_since_cancel: int
    max_days_since_cancel: int
    eligible_cancel_reasons: List[str]
    campaign_status: str
    created_at: str
    updated_at: str
    version: int


class PartnerBillingRecord(TypedDict, total=False):
    partner_billing_record_id: str
    partner_code: str
    account_id: str
    partner_subscription_ref: str
    report_status: str
    expected_amount_cents: int
    received_amount_cents: int
    period_start_utc: str
    period_end_utc: str
    created_at: str
    updated_at: str
    version: int


class SignupAttribution(TypedDict, total=False):
    signup_attribution_id: str
    account_id: str
    subscription_id: str
    content_id: str
    channel: str
    cohort_month: str
    retained_at_day_30: bool
    retained_at_day_90: bool
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry: ONLY id + created_at from the common set
# (PRD section 2.5 — no updated_at, no version).
class BillingEvent(TypedDict, total=False):
    billing_event_id: str
    account_id: str
    subscription_id: str
    event_type: str
    amount_cents: int
    occurred_at_utc: str
    external_reference: Optional[str]
    notes: Optional[str]
    created_at: str
