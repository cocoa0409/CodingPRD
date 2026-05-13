"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Per PRD §2.4 each entity has one of
two shapes:

- Versioned (id + created_at + updated_at + version): Work, RightsHolder,
  AgencyBinding, RightsShare, PlaybackBatch, RoyaltyPool, Distribution,
  MicroBalance, Dispute, PayoutBatch, Payment.

- Append-only (id + created_at ONLY; NO updated_at, NO version):
  ShareChangeAudit, PlaybackEvent, DistributionRuleVersion,
  ExternalSyncEvent.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RIGHTS_HOLDER = "RightsHolder"
    REGISTRATION_REVIEWER = "RegistrationReviewer"
    FINANCE_OPS = "FinanceOps"
    DISPUTE_OFFICER = "DisputeOfficer"
    PLAYBACK_SOURCE = "PlaybackSource"


# ---------------------------------------------------------------------------
# Work-related enums (PRD §3.1, §3.2, §3.11)
# ---------------------------------------------------------------------------
class WorkRegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class WorkDisputePosture(str, Enum):
    CLEAR = "CLEAR"
    FROZEN = "FROZEN"


class WorkRightsType(str, Enum):
    COMPOSITION = "COMPOSITION"
    LYRICS = "LYRICS"
    RECORDING = "RECORDING"
    PERFORMANCE = "PERFORMANCE"


class CoCreatorRole(str, Enum):
    COMPOSER = "COMPOSER"
    LYRICIST = "LYRICIST"
    PRODUCER = "PRODUCER"
    PERFORMER = "PERFORMER"


# ---------------------------------------------------------------------------
# RightsHolder enums (PRD §3.5)
# ---------------------------------------------------------------------------
class HolderKind(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    ORGANIZATION = "ORGANIZATION"


class PayoutCurrency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CNY = "CNY"


# ---------------------------------------------------------------------------
# AgencyBinding enums (PRD §3.4)
# ---------------------------------------------------------------------------
class AgencyKind(str, Enum):
    PUBLISHER = "PUBLISHER"
    LABEL = "LABEL"
    CMO = "CMO"


class AgencyBindingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


# ---------------------------------------------------------------------------
# RightsShare enums (PRD §3.3)
# ---------------------------------------------------------------------------
class ShareStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISPUTED = "DISPUTED"
    TERMINATED = "TERMINATED"


class ShareChangeKind(str, Enum):
    CREATED = "CREATED"
    PERCENT_UPDATED = "PERCENT_UPDATED"
    STATUS_TRANSITION = "STATUS_TRANSITION"
    AGENCY_REBOUND = "AGENCY_REBOUND"
    TERMINATED = "TERMINATED"


# ---------------------------------------------------------------------------
# PlaybackBatch / PlaybackEvent enums (PRD §3.6)
# ---------------------------------------------------------------------------
class PlaybackChannel(str, Enum):
    STREAMING = "STREAMING"
    RADIO = "RADIO"
    TV = "TV"
    PUBLIC_VENUE = "PUBLIC_VENUE"
    LIVE = "LIVE"


class PlaybackBatchValidity(str, Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    INVALID_RANGE = "INVALID_RANGE"
    DEDUPED_REJECTED = "DEDUPED_REJECTED"


class PlaybackEventStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE_DROPPED = "DUPLICATE_DROPPED"
    SUPPLEMENTED = "SUPPLEMENTED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# RoyaltyPool enums (PRD §3.8, §3.10)
# ---------------------------------------------------------------------------
class RevenueSource(str, Enum):
    STREAMING = "STREAMING"
    RADIO = "RADIO"
    TV = "TV"
    PUBLIC_VENUE = "PUBLIC_VENUE"
    LIVE = "LIVE"
    SYNC = "SYNC"
    MECHANICAL_LICENSE = "MECHANICAL_LICENSE"


class RoyaltyPoolStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DISTRIBUTED = "DISTRIBUTED"


# ---------------------------------------------------------------------------
# Distribution enums (PRD §3.9, §3.13, §3.14)
# ---------------------------------------------------------------------------
class DistributionStatus(str, Enum):
    PENDING = "PENDING"
    FROZEN = "FROZEN"
    RELEASED = "RELEASED"
    PAID = "PAID"
    FORFEITED = "FORFEITED"


class DistributionSubPool(str, Enum):
    MECHANICAL = "MECHANICAL"
    PERFORMANCE = "PERFORMANCE"


# ---------------------------------------------------------------------------
# DistributionRuleVersion enums (PRD §3.7)
# ---------------------------------------------------------------------------
class DistributionMode(str, Enum):
    PER_PLAY = "PER_PLAY"
    PER_DURATION = "PER_DURATION"
    HYBRID = "HYBRID"


# ---------------------------------------------------------------------------
# Dispute enums (PRD §3.11)
# ---------------------------------------------------------------------------
class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    MEDIATION = "MEDIATION"
    ARBITRATION = "ARBITRATION"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_DISMISSED = "RESOLVED_DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class DisputeKind(str, Enum):
    SHARE_RATIO = "SHARE_RATIO"
    OWNERSHIP = "OWNERSHIP"
    ORIGINALITY = "ORIGINALITY"
    AGENCY_AUTHORITY = "AGENCY_AUTHORITY"


class DisputeOutcome(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


# ---------------------------------------------------------------------------
# PayoutBatch / Payment enums (PRD §3.12, §3.13)
# ---------------------------------------------------------------------------
class PayoutBatchStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PaymentStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    ABANDONED = "ABANDONED"


class RoutingChannel(str, Enum):
    SWIFT = "SWIFT"
    SEPA = "SEPA"
    ACH = "ACH"
    LOCAL_JP = "LOCAL_JP"
    LOCAL_CN = "LOCAL_CN"


# ---------------------------------------------------------------------------
# ExternalSyncEvent enums (PRD §3.14)
# ---------------------------------------------------------------------------
class ExternalTargetSystem(str, Enum):
    PAYMENT_PSP = "PAYMENT_PSP"
    BANK = "BANK"
    CMO_GATEWAY = "CMO_GATEWAY"


class ExternalEventKind(str, Enum):
    PAYMENT_INITIATED = "PAYMENT_INITIATED"
    PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    BANK_RECONCILIATION = "BANK_RECONCILIATION"
    CMO_SHARE_PUSH = "CMO_SHARE_PUSH"
    CMO_REVENUE_PULL = "CMO_REVENUE_PULL"


class RelatedEntityKind(str, Enum):
    PAYMENT = "Payment"
    PAYOUT_BATCH = "PayoutBatch"
    RIGHTS_SHARE = "RightsShare"
    ROYALTY_POOL = "RoyaltyPool"


# ===========================================================================
# Entity TypedDicts.
# Versioned entities carry id + created_at + updated_at + version.
# Append-only entities carry ONLY id + created_at.
# ===========================================================================

# ---------- Versioned: Work ----------
class Work(TypedDict, total=False):
    id: str
    title: str
    duration_seconds: int
    isrc: Optional[str]
    iswc: Optional[str]
    rights_type: str
    co_creators: List[Dict[str, Any]]
    original_proof_url: str
    registration_status: str
    dispute_posture: str
    reject_reason: Optional[str]
    reviewer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------- Versioned: RightsHolder ----------
class RightsHolder(TypedDict, total=False):
    id: str
    legal_name: str
    holder_kind: str
    date_of_birth: Optional[str]
    is_minor: bool
    guardian_holder_id: Optional[str]
    tax_jurisdiction: str
    payout_currency: str
    bank_account_token: str
    created_at: str
    updated_at: str
    version: int


# ---------- Versioned: AgencyBinding ----------
class AgencyBinding(TypedDict, total=False):
    id: str
    rights_holder_id: str
    agency_kind: str
    agency_name: str
    territory: str
    commission_percent: float
    effective_from: str
    effective_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------- Versioned: RightsShare ----------
class RightsShare(TypedDict, total=False):
    id: str
    work_id: str
    rights_holder_id: str
    share_percent: float
    share_status: str
    agency_binding_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------- Append-only: ShareChangeAudit ----------
class ShareChangeAudit(TypedDict, total=False):
    id: str
    rights_share_id: str
    changed_by_role: str
    changed_by_id: str
    change_kind: str
    before_snapshot: Optional[Dict[str, Any]]
    after_snapshot: Dict[str, Any]
    created_at: str


# ---------- Versioned: PlaybackBatch ----------
class PlaybackBatch(TypedDict, total=False):
    id: str
    channel: str
    source_signature: str
    source_identifier: str
    reporting_period_start: str
    reporting_period_end: str
    validity_status: str
    total_events_submitted: int
    total_events_accepted: int
    created_at: str
    updated_at: str
    version: int


# ---------- Append-only: PlaybackEvent ----------
class PlaybackEvent(TypedDict, total=False):
    id: str
    playback_batch_id: str
    work_id: Optional[str]
    isrc: Optional[str]
    iswc: Optional[str]
    played_at: str
    play_duration_seconds: int
    region: str
    dedup_key: str
    status: str
    created_at: str


# ---------- Versioned: RoyaltyPool ----------
class RoyaltyPool(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    revenue_source: str
    region: str
    gross_revenue_cents: int
    platform_share_percent: float
    pool_currency: str
    net_distributable_cents: int
    mechanical_split_percent: float
    status: str
    distribution_rule_version_id: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------- Append-only: DistributionRuleVersion ----------
class DistributionRuleVersion(TypedDict, total=False):
    id: str
    version_tag: str
    channel: str
    distribution_mode: str
    per_play_weight: Optional[float]
    per_duration_weight: Optional[float]
    playback_type_weights: Dict[str, float]
    minimum_payout_cents: int
    micro_accumulation_cap_cents: int
    effective_from: str
    created_at: str


# ---------- Versioned: Distribution ----------
class Distribution(TypedDict, total=False):
    id: str
    royalty_pool_id: str
    work_id: str
    rights_holder_id: str
    rights_share_id: str
    sub_pool: str
    gross_amount_cents: int
    commission_cents: int
    net_after_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------- Versioned: MicroBalance ----------
class MicroBalance(TypedDict, total=False):
    id: str
    rights_holder_id: str
    currency: str
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


# ---------- Versioned: Dispute ----------
class Dispute(TypedDict, total=False):
    id: str
    work_id: str
    claimant_rights_holder_id: str
    dispute_kind: str
    claim_summary: str
    status: str
    evidence_items: List[Dict[str, Any]]
    arbitration_decision: Optional[str]
    arbitrator_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------- Versioned: PayoutBatch ----------
class PayoutBatch(TypedDict, total=False):
    id: str
    cycle_tag: str
    scheduled_run_at: str
    status: str
    total_payments: int
    total_paid_cents_by_currency: Dict[str, int]
    created_at: str
    updated_at: str
    version: int


# ---------- Versioned: Payment ----------
class Payment(TypedDict, total=False):
    id: str
    payout_batch_id: str
    rights_holder_id: str
    currency: str
    gross_cents: int
    tax_withheld_cents: int
    net_payable_cents: int
    routing_channel: str
    status: str
    retry_count: int
    last_failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------- Append-only: ExternalSyncEvent ----------
class ExternalSyncEvent(TypedDict, total=False):
    id: str
    target_system: str
    event_kind: str
    related_entity_kind: str
    related_entity_id: str
    payload: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "WorkRegistrationStatus", "WorkDisputePosture", "WorkRightsType",
    "CoCreatorRole",
    "HolderKind", "PayoutCurrency",
    "AgencyKind", "AgencyBindingStatus",
    "ShareStatus", "ShareChangeKind",
    "PlaybackChannel", "PlaybackBatchValidity", "PlaybackEventStatus",
    "RevenueSource", "RoyaltyPoolStatus",
    "DistributionStatus", "DistributionSubPool",
    "DistributionMode",
    "DisputeStatus", "DisputeKind", "DisputeOutcome",
    "PayoutBatchStatus", "PaymentStatus", "RoutingChannel",
    "ExternalTargetSystem", "ExternalEventKind", "RelatedEntityKind",
    "Work", "RightsHolder", "AgencyBinding", "RightsShare",
    "ShareChangeAudit",
    "PlaybackBatch", "PlaybackEvent",
    "RoyaltyPool", "DistributionRuleVersion", "Distribution",
    "MicroBalance", "Dispute",
    "PayoutBatch", "Payment", "ExternalSyncEvent",
]
