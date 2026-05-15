"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4: Advertiser, AccountUser, Campaign, AdGroup, Creative carry
id/created_at/updated_at/version. QualificationDoc, AuctionEvent,
BillingEvent, ConversionEvent, WalletTransaction, ReviewDecision, and
AuditLog are append-only — they carry only id and created_at; no
updated_at and no version on those entities.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_OWNER = "AccountOwner"
    CAMPAIGN_MANAGER = "CampaignManager"
    FINANCE_OFFICER = "FinanceOfficer"
    CREATIVE_REVIEWER = "CreativeReviewer"
    EXCHANGE_SERVICE = "ExchangeService"
    MEASUREMENT_PARTNER = "MeasurementPartner"
    ANTI_FRAUD_SERVICE = "AntiFraudService"


# ---------------------------------------------------------------------------
# Advertiser (PRD §2.5)
# ---------------------------------------------------------------------------
class AdvertiserStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AdvertiserBalanceState(str, Enum):
    HEALTHY = "HEALTHY"
    LOW_BALANCE = "LOW_BALANCE"
    ZERO_BALANCE = "ZERO_BALANCE"


class AdvertiserQualificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AccountType(str, Enum):
    MCC = "MCC"
    SUB_ACCOUNT = "SUB_ACCOUNT"
    INDEPENDENT = "INDEPENDENT"


class IndustryCategory(str, Enum):
    GENERAL = "GENERAL"
    MEDICAL = "MEDICAL"
    FINANCIAL = "FINANCIAL"
    EDUCATION = "EDUCATION"


class BillingMode(str, Enum):
    PREPAY = "PREPAY"
    POSTPAY = "POSTPAY"


# ---------------------------------------------------------------------------
# AccountUser (PRD §2.5, §3.2)
# ---------------------------------------------------------------------------
class AccountRole(str, Enum):
    OWNER = "OWNER"
    CAMPAIGN_MANAGER = "CAMPAIGN_MANAGER"
    FINANCE = "FINANCE"
    VIEWER = "VIEWER"


class AccountUserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


# ---------------------------------------------------------------------------
# Campaign (PRD §2.5)
# ---------------------------------------------------------------------------
class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ENDED = "ENDED"


class PacingStrategy(str, Enum):
    STANDARD = "STANDARD"
    ACCELERATED = "ACCELERATED"


# ---------------------------------------------------------------------------
# AdGroup (PRD §2.5)
# ---------------------------------------------------------------------------
class AdGroupStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DISAPPROVED = "DISAPPROVED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ARCHIVED = "ARCHIVED"


class BiddingStrategy(str, Enum):
    CPC = "CPC"
    CPM = "CPM"
    CPA = "CPA"
    OCPX = "OCPX"


class TargetingDevice(str, Enum):
    DESKTOP = "DESKTOP"
    MOBILE = "MOBILE"
    TABLET = "TABLET"
    CTV = "CTV"


# ---------------------------------------------------------------------------
# Creative (PRD §2.5)
# ---------------------------------------------------------------------------
class CreativeReviewStatus(str, Enum):
    PENDING_PRESCREEN = "PENDING_PRESCREEN"
    PRESCREEN_FAILED = "PRESCREEN_FAILED"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPEAL_FILED = "APPEAL_FILED"
    UNDER_APPEAL_REVIEW = "UNDER_APPEAL_REVIEW"
    ARCHIVED = "ARCHIVED"


class CreativeFormat(str, Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    NATIVE = "NATIVE"
    HTML5 = "HTML5"


# ---------------------------------------------------------------------------
# QualificationDoc (PRD §2.5)
# ---------------------------------------------------------------------------
class QualificationDocStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class QualificationDocType(str, Enum):
    BUSINESS_LICENSE = "BUSINESS_LICENSE"
    MEDICAL_PERMIT = "MEDICAL_PERMIT"
    FINANCIAL_LICENSE = "FINANCIAL_LICENSE"
    EDUCATION_PERMIT = "EDUCATION_PERMIT"


# ---------------------------------------------------------------------------
# AuctionEvent (PRD §2.5, §3.5)
# ---------------------------------------------------------------------------
class AuctionExchange(str, Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL_RTB = "EXTERNAL_RTB"


class PricingRule(str, Enum):
    GSP = "GSP"
    VCG = "VCG"


class AuctionDevice(str, Enum):
    DESKTOP = "DESKTOP"
    MOBILE = "MOBILE"
    TABLET = "TABLET"
    CTV = "CTV"


class AuctionOutcome(str, Enum):
    FILLED = "FILLED"
    NO_BID = "NO_BID"
    FLOOR_NOT_MET = "FLOOR_NOT_MET"
    ALL_FILTERED = "ALL_FILTERED"


# ---------------------------------------------------------------------------
# BillingEvent (PRD §2.5, §3.6)
# ---------------------------------------------------------------------------
class BillingEventStatus(str, Enum):
    PENDING_IVT = "PENDING_IVT"
    VALID = "VALID"
    INVALID_TRAFFIC = "INVALID_TRAFFIC"
    DEDUPLICATED = "DEDUPLICATED"
    FINALIZED = "FINALIZED"
    REVERSED = "REVERSED"


class BillingEventType(str, Enum):
    IMPRESSION = "IMPRESSION"
    CLICK = "CLICK"
    CONVERSION = "CONVERSION"


# ---------------------------------------------------------------------------
# ConversionEvent (PRD §2.5, §3.7)
# ---------------------------------------------------------------------------
class ConversionAttributionStatus(str, Enum):
    PENDING = "PENDING"
    ATTRIBUTED = "ATTRIBUTED"
    UNATTRIBUTED = "UNATTRIBUTED"


class ConversionSource(str, Enum):
    WEB_PIXEL = "WEB_PIXEL"
    APP_SDK = "APP_SDK"
    S2S = "S2S"
    OFFLINE_UPLOAD = "OFFLINE_UPLOAD"


class AttributionModel(str, Enum):
    LAST_CLICK = "LAST_CLICK"
    POSITION_BASED = "POSITION_BASED"
    DATA_DRIVEN = "DATA_DRIVEN"


# ---------------------------------------------------------------------------
# WalletTransaction (PRD §2.5, §3.8)
# ---------------------------------------------------------------------------
class WalletTxStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class WalletTxType(str, Enum):
    RECHARGE = "RECHARGE"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"
    INVOICE_SETTLEMENT = "INVOICE_SETTLEMENT"
    CONSUMPTION = "CONSUMPTION"


# ---------------------------------------------------------------------------
# ReviewDecision (PRD §2.5, §3.4)
# ---------------------------------------------------------------------------
class ReviewDecisionType(str, Enum):
    PRESCREEN = "PRESCREEN"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    APPEAL_DECISION = "APPEAL_DECISION"


class ReviewDecisionOutcome(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.5, §3.4)
# ---------------------------------------------------------------------------
class AuditLogAction(str, Enum):
    REVIEW_DECISION = "REVIEW_DECISION"
    BALANCE_ADJUSTMENT = "BALANCE_ADJUSTMENT"
    REFUND = "REFUND"
    CREDIT_LINE_CHANGE = "CREDIT_LINE_CHANGE"
    ACCOUNT_STATUS_CHANGE = "ACCOUNT_STATUS_CHANGE"


# ===========================================================================
# Entity TypedDicts — fields the implementation must surface in responses.
# ===========================================================================

# Common-fields entities — PRD §2.4 says these carry id, created_at,
# updated_at, version.
class Advertiser(TypedDict, total=False):
    id: str
    parent_account_id: Optional[str]
    account_type: str
    legal_name: str
    business_license_number: str
    industry_category: str
    special_qualifications: List[str]
    qualification_status: str
    status: str
    billing_mode: str
    credit_line_cents: int
    balance_cents: int
    consumed_cents: int
    balance_state: str
    low_balance_threshold_cents: int
    tax_rate_bps: int
    created_at: str
    updated_at: str
    version: int


class AccountUser(TypedDict, total=False):
    id: str
    advertiser_id: str
    external_user_id: str
    account_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    advertiser_id: str
    name: str
    daily_budget_cents: int
    lifetime_budget_cents: Optional[int]
    pacing_strategy: str
    status: str
    start_date: str
    end_date: Optional[str]
    lifetime_spent_cents: int
    today_spent_cents: int
    created_at: str
    updated_at: str
    version: int


class AdGroup(TypedDict, total=False):
    id: str
    campaign_id: str
    advertiser_id: str
    name: str
    bidding_strategy: str
    bid_cents: int
    targeting_geo: List[str]
    targeting_demographic: Optional[Dict[str, Any]]
    targeting_interest: List[str]
    targeting_behavior: List[str]
    targeting_device: List[str]
    targeting_dayparts: List[Dict[str, Any]]
    remarketing_audience_id: Optional[str]
    frequency_cap_per_user_per_day: Optional[int]
    status: str
    quality_score: float
    predicted_ctr: float
    approved_creative_count: int
    created_at: str
    updated_at: str
    version: int


class Creative(TypedDict, total=False):
    id: str
    ad_group_id: str
    advertiser_id: str
    format: str
    asset_url: str
    headline: str
    body_text: str
    landing_url: str
    required_disclaimer: Optional[str]
    version_number: int
    parent_version_id: Optional[str]
    review_status: str
    pre_screen_score: Optional[float]
    rejection_codes: List[str]
    appeal_count: int
    archived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only entities — PRD §2.4 says these carry ONLY id and created_at.
# These TypedDicts intentionally OMIT updated_at and version.
class QualificationDoc(TypedDict, total=False):
    id: str
    advertiser_id: str
    doc_type: str
    doc_url: str
    expiry_date: str
    review_status: str
    rejection_reason: Optional[str]
    created_at: str


class AuctionEvent(TypedDict, total=False):
    id: str
    exchange: str
    pricing_rule: str
    floor_price_cents: int
    user_id: str
    device: str
    geo: str
    candidate_ad_group_ids: List[str]
    filtered_ad_group_ids: List[str]
    winning_ad_group_id: Optional[str]
    winning_creative_id: Optional[str]
    clearing_price_cents: int
    bid_shaded: bool
    outcome: str
    created_at: str


class BillingEvent(TypedDict, total=False):
    id: str
    event_type: str
    auction_event_id: str
    ad_group_id: str
    campaign_id: str
    advertiser_id: str
    dedup_key: str
    gross_cost_cents: int
    tax_cents: int
    cost_cents: int
    ivt_score: float
    status: str
    finalized_at: Optional[str]
    reversal_reason: Optional[str]
    created_at: str


class ConversionEvent(TypedDict, total=False):
    id: str
    source: str
    user_id: str
    advertiser_id: str
    conversion_type: str
    value_cents: int
    attribution_window_days: int
    attribution_model: str
    attributed_touchpoints: List[Dict[str, Any]]
    attribution_status: str
    created_at: str


class WalletTransaction(TypedDict, total=False):
    id: str
    advertiser_id: str
    tx_type: str
    amount_cents: int
    reference_event_id: Optional[str]
    status: str
    idempotency_key: str
    note: Optional[str]
    created_at: str


class ReviewDecision(TypedDict, total=False):
    id: str
    creative_id: str
    decision_type: str
    reviewer_user_id: str
    outcome: str
    rejection_codes: List[str]
    notes: Optional[str]
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_user_id: str
    actor_role: str
    action: str
    target_entity_type: str
    target_entity_id: str
    before_value: Optional[Dict[str, Any]]
    after_value: Optional[Dict[str, Any]]
    created_at: str


__all__ = [
    # Roles
    "UserRole",
    # Advertiser enums
    "AdvertiserStatus",
    "AdvertiserBalanceState",
    "AdvertiserQualificationStatus",
    "AccountType",
    "IndustryCategory",
    "BillingMode",
    # AccountUser enums
    "AccountRole",
    "AccountUserStatus",
    # Campaign enums
    "CampaignStatus",
    "PacingStrategy",
    # AdGroup enums
    "AdGroupStatus",
    "BiddingStrategy",
    "TargetingDevice",
    # Creative enums
    "CreativeReviewStatus",
    "CreativeFormat",
    # Qualification doc enums
    "QualificationDocStatus",
    "QualificationDocType",
    # Auction enums
    "AuctionExchange",
    "PricingRule",
    "AuctionDevice",
    "AuctionOutcome",
    # BillingEvent enums
    "BillingEventStatus",
    "BillingEventType",
    # Conversion enums
    "ConversionAttributionStatus",
    "ConversionSource",
    "AttributionModel",
    # Wallet enums
    "WalletTxStatus",
    "WalletTxType",
    # Review enums
    "ReviewDecisionType",
    "ReviewDecisionOutcome",
    # Audit enums
    "AuditLogAction",
    # Entity types
    "Advertiser",
    "AccountUser",
    "Campaign",
    "AdGroup",
    "Creative",
    "QualificationDoc",
    "AuctionEvent",
    "BillingEvent",
    "ConversionEvent",
    "WalletTransaction",
    "ReviewDecision",
    "AuditLog",
]
