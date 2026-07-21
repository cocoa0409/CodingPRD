"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource model. Monetary quantities are whole integer
cents everywhere (PRD §2.6).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─────────────────────────── Status enums ───────────────────────────

class MerchantStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CardProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class IncentiveCampaignStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    ENDED = "ENDED"


class CardBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    CANCELLED = "CANCELLED"


class CardBatchChannel(str, Enum):
    DIGITAL = "DIGITAL"
    PHYSICAL = "PHYSICAL"


class CardBatchPurpose(str, Enum):
    RETAIL = "RETAIL"
    B2B_BULK = "B2B_BULK"
    INCENTIVE = "INCENTIVE"


class GiftCardStatus(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    ESCHEATED = "ESCHEATED"
    CLOSED = "CLOSED"


class LedgerEntryType(str, Enum):
    ACTIVATION_LOAD = "ACTIVATION_LOAD"
    RELOAD = "RELOAD"
    INCENTIVE_BONUS = "INCENTIVE_BONUS"
    REDEMPTION = "REDEMPTION"
    DORMANCY_FEE = "DORMANCY_FEE"
    BREAKAGE = "BREAKAGE"
    ESCHEAT_REMIT = "ESCHEAT_REMIT"


class LedgerEntryStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class FraudHoldStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    CONFIRMED = "CONFIRMED"


class FraudHoldReason(str, Enum):
    VELOCITY = "VELOCITY"
    MANUAL = "MANUAL"
    CHARGEBACK = "CHARGEBACK"


class SettlementBatchStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class EscheatReportStatus(str, Enum):
    DRAFT = "DRAFT"
    REMITTED = "REMITTED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MERCHANT_ADMIN = "MerchantAdmin"
    POS_TERMINAL = "POSTerminal"
    FRAUD_ANALYST = "FraudAnalyst"
    SETTLEMENT_OFFICER = "SettlementOfficer"
    ANY = "Any"


# ─────────────────────────── Entity TypedDicts ───────────────────────────
# Entities carrying id + created_at + updated_at + version (PRD §2.5).

class Merchant(TypedDict):
    id: str
    legal_name: str
    settlement_currency: str
    status: str
    unsettled_redemptions_cents: int
    lifetime_net_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class CardProgram(TypedDict):
    id: str
    merchant_id: str
    name: str
    currency: str
    breakage_method: str
    expiry_months: int
    max_balance_cents: int
    min_load_cents: int
    status: str
    outstanding_balance_cents: int
    breakage_recognized_cents: int
    created_at: str
    updated_at: str
    version: int


class IncentiveCampaign(TypedDict):
    id: str
    card_program_id: str
    name: str
    bonus_bps: int
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CardBatch(TypedDict):
    id: str
    card_program_id: str
    channel: str
    card_count: int
    unit_load_cents: int
    purpose: str
    status: str
    committed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GiftCard(TypedDict):
    id: str
    card_program_id: str
    card_batch_id: str
    incentive_campaign_id: Optional[str]
    card_number: str
    channel: str
    status: str
    balance_cents: int
    initial_load_cents: int
    activated_at: Optional[str]
    expires_at: Optional[str]
    last_activity_at: Optional[str]
    dormant: bool
    created_at: str
    updated_at: str
    version: int


class FraudHold(TypedDict):
    id: str
    gift_card_id: str
    reason: str
    opened_by_user_id: str
    resolved_by_user_id: Optional[str]
    status: str
    reversed_redemption_count: int
    created_at: str
    updated_at: str
    version: int


class VelocityRule(TypedDict):
    id: str
    card_program_id: str
    window_hours: int
    max_count: int
    max_amount_cents: int
    enabled: bool
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict):
    id: str
    merchant_id: str
    period_start: str
    period_end: str
    opened_by_user_id: str
    finalized_by_user_id: Optional[str]
    status: str
    gross_redemptions_cents: int
    interchange_fee_cents: int
    net_payout_cents: int
    provisional_net_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class EscheatReport(TypedDict):
    id: str
    merchant_id: str
    jurisdiction: str
    period_start: str
    period_end: str
    status: str
    escheat_total_cents: int
    card_count: int
    created_at: str
    updated_at: str
    version: int


# LedgerEntry is the sole append-only record: id + created_at only (PRD §2.5).
# No updated_at, no version.
class LedgerEntry(TypedDict):
    id: str
    gift_card_id: str
    settlement_batch_id: Optional[str]
    entry_type: str
    amount_cents: int
    status: str
    memo: str
    created_at: str
