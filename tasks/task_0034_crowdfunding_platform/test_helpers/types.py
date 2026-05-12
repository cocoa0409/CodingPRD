"""Domain types for the Crowdfunding Platform API.

Status enums and entity TypedDicts derived from PRD §2.4 (Common Resource
Properties) and §3 entity prose.

PRD §2.4 distinguishes two field-shape classes:
- Standard resources (Initiator, Backer, Project, Reward, AddOnItem, Order,
  RefundRequest, SettlementBatch) carry id, created_at, updated_at, version.
- Append-only entries (ProgressUpdate, AuditLogEntry, EscrowLedgerEntry)
  carry only id and created_at — tests MUST NOT assert updated_at or version
  on these.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    INITIATOR = "Initiator"
    BACKER = "Backer"
    CONTENT_REVIEWER = "ContentReviewer"
    LEGAL_REVIEWER = "LegalReviewer"
    FINANCIAL_REVIEWER = "FinancialReviewer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class KycStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    CONTENT_REVIEW = "CONTENT_REVIEW"
    LEGAL_REVIEW = "LEGAL_REVIEW"
    FINANCIAL_REVIEW = "FINANCIAL_REVIEW"
    REJECTED = "REJECTED"
    LIVE = "LIVE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FundingModel(str, Enum):
    ALL_OR_NOTHING = "ALL_OR_NOTHING"
    KEEP_IT_ALL = "KEEP_IT_ALL"


class ProjectCategory(str, Enum):
    TECH = "TECH"
    ART = "ART"
    COMMUNITY = "COMMUNITY"


class RewardType(str, Enum):
    PHYSICAL = "PHYSICAL"
    DIGITAL = "DIGITAL"


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CHARGE_PENDING = "CHARGE_PENDING"
    CHARGED = "CHARGED"
    CHARGE_FAILED = "CHARGE_FAILED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    VOIDED = "VOIDED"


class FulfillmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    FULLY_SHIPPED = "FULLY_SHIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RefundReason(str, Enum):
    PROJECT_FAILED = "PROJECT_FAILED"
    PROJECT_CANCELLED = "PROJECT_CANCELLED"
    DISPUTE = "DISPUTE"
    PLATFORM_MANDATORY = "PLATFORM_MANDATORY"


class RefundStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class RefundTriggeredBy(str, Enum):
    BACKER = "BACKER"
    INITIATOR = "INITIATOR"
    PLATFORM_AUTO = "PLATFORM_AUTO"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    FAILED = "FAILED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"


class ProgressVisibility(str, Enum):
    PUBLIC = "PUBLIC"
    BACKERS_ONLY = "BACKERS_ONLY"


class AuditSubjectType(str, Enum):
    PROJECT = "PROJECT"
    ORDER = "ORDER"
    REFUND_REQUEST = "REFUND_REQUEST"
    SETTLEMENT_BATCH = "SETTLEMENT_BATCH"
    ESCROW_LEDGER = "ESCROW_LEDGER"


class AuditEventType(str, Enum):
    STATUS_CHANGE = "STATUS_CHANGE"
    FUND_FLOW = "FUND_FLOW"
    REFUND_EXECUTED = "REFUND_EXECUTED"
    SETTLEMENT_PAID = "SETTLEMENT_PAID"
    REVIEW_DECISION = "REVIEW_DECISION"
    EXTERNAL_EVENT_RECEIVED = "EXTERNAL_EVENT_RECEIVED"


class EscrowEntryType(str, Enum):
    AUTH_HOLD = "AUTH_HOLD"
    CHARGE_CAPTURE = "CHARGE_CAPTURE"
    CHARGE_VOID = "CHARGE_VOID"
    REFUND_OUT = "REFUND_OUT"
    COMMISSION_HOLD = "COMMISSION_HOLD"
    COMMISSION_REVERSAL = "COMMISSION_REVERSAL"
    CHANNEL_FEE = "CHANNEL_FEE"
    SETTLEMENT_PAYOUT = "SETTLEMENT_PAYOUT"


class PaymentEventResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


# ---------------------------------------------------------------------------
# Standard (versioned) entity TypedDicts
# ---------------------------------------------------------------------------
class Initiator(TypedDict, total=False):
    id: str
    legal_name: str
    kyc_status: str
    tax_id: Optional[str]
    bank_account_id: Optional[str]
    qualification_doc_uri: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Backer(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    default_shipping_address: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    initiator_id: str
    title: str
    category: str
    description_md: str
    media_uris: List[str]
    risk_disclosure: str
    funding_model: str
    funding_target_cents: int
    deadline: str
    status: str
    provisional_raised_cents: int
    final_raised_cents: int
    rejection_reason: Optional[str]
    last_update_published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reward(TypedDict, total=False):
    id: str
    project_id: str
    tier_label: str
    pledge_amount_cents: int
    reward_type: str
    inventory_limit: Optional[int]
    inventory_claimed: int
    estimated_delivery: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AddOnItem(TypedDict, total=False):
    id: str
    project_id: str
    name: str
    price_cents: int
    requires_shipping: bool
    inventory_limit: Optional[int]
    inventory_claimed: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    project_id: str
    backer_id: str
    reward_id: str
    add_ons: List[Dict[str, Any]]
    shipping_address: Optional[Dict[str, Any]]
    payment_method_token: str
    pledge_amount_cents: int
    add_ons_total_cents: int
    order_total_cents: int
    payment_status: str
    fulfillment_status: str
    charge_attempts: int
    order_modification_locked_at: str
    refundable_remainder_cents: int
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict, total=False):
    id: str
    order_id: str
    reason: str
    requested_amount_cents: int
    status: str
    approved_amount_cents: Optional[int]
    rejection_reason: Optional[str]
    triggered_by: str
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict, total=False):
    id: str
    project_id: str
    period_start: str
    period_end: str
    gross_charged_cents: int
    commission_cents: int
    channel_fee_cents: int
    refund_reversal_cents: int
    tax_withheld_cents: int
    net_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entity TypedDicts (no updated_at / no version per PRD §2.4)
# ---------------------------------------------------------------------------
class ProgressUpdate(TypedDict, total=False):
    id: str
    project_id: str
    title: str
    body_md: str
    visibility: str
    milestone_label: Optional[str]
    is_delay_notice: bool
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    event_type: str
    payload: Dict[str, Any]
    actor_role: str
    actor_id: str
    created_at: str


class EscrowLedgerEntry(TypedDict, total=False):
    id: str
    project_id: str
    order_id: Optional[str]
    entry_type: str
    amount_cents: int
    external_ref: Optional[str]
    created_at: str


__all__ = [
    "UserRole",
    "KycStatus",
    "ProjectStatus",
    "FundingModel",
    "ProjectCategory",
    "RewardType",
    "PaymentStatus",
    "FulfillmentStatus",
    "RefundReason",
    "RefundStatus",
    "RefundTriggeredBy",
    "SettlementStatus",
    "ReviewDecision",
    "ProgressVisibility",
    "AuditSubjectType",
    "AuditEventType",
    "EscrowEntryType",
    "PaymentEventResult",
    "Initiator",
    "Backer",
    "Project",
    "Reward",
    "AddOnItem",
    "Order",
    "RefundRequest",
    "SettlementBatch",
    "ProgressUpdate",
    "AuditLogEntry",
    "EscrowLedgerEntry",
]
