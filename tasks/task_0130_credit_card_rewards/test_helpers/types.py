"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Persisted/mutating resources — Cardholder, Account, CashbackCategory,
  Transaction, TransferPartner — carry id, created_at, updated_at, and
  version (PRD §2.4: "Every primary resource ... exposes the same four
  system-managed fields: an id ..., a created_at ..., an updated_at ...,
  and an integer version ...").

- Append-only resources — QuarterlyActivation, PointsTransfer,
  StatementCredit, PointsLedgerEntry — carry ONLY id and created_at
  (PRD §2.4: "Four resources are append-only in this system and carry
  only id and created_at, with both updated_at and version absent from
  their JSON shape: QuarterlyActivation, PointsTransfer,
  StatementCredit, and PointsLedgerEntry.").
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CARDHOLDER = "Cardholder"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Account lifecycle dimension — PRD §3.1 / §2.10
# ---------------------------------------------------------------------------
class AccountLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Account spending-tier dimension — PRD §2.10 / §3.5
# ---------------------------------------------------------------------------
class SpendingTier(str, Enum):
    STANDARD = "STANDARD"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


# ---------------------------------------------------------------------------
# Account signup-bonus dimension — PRD §3.1
# ---------------------------------------------------------------------------
class SignupBonusState(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    AWARDED = "AWARDED"
    EXPIRED = "EXPIRED"
    FORFEITED = "FORFEITED"


# ---------------------------------------------------------------------------
# CashbackCategory enumerations — PRD §3.2
# ---------------------------------------------------------------------------
class CategoryType(str, Enum):
    BASELINE = "BASELINE"
    FIXED_BONUS = "FIXED_BONUS"
    ROTATING_QUARTERLY = "ROTATING_QUARTERLY"


# ---------------------------------------------------------------------------
# Transaction enumerations — PRD §3.4
# ---------------------------------------------------------------------------
class TxnType(str, Enum):
    PURCHASE = "PURCHASE"
    REFUND = "REFUND"


class TransactionStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# TransferPartner enumerations — PRD §3.3
# ---------------------------------------------------------------------------
class PartnerType(str, Enum):
    AIRLINE = "AIRLINE"
    HOTEL = "HOTEL"


# ---------------------------------------------------------------------------
# PointsTransfer status — PRD §3.7
# ---------------------------------------------------------------------------
class PointsTransferStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# StatementCredit enumerations — PRD §3.6
# ---------------------------------------------------------------------------
class RedemptionMode(str, Enum):
    POINTS_FIRST = "POINTS_FIRST"
    AMOUNT_FIRST = "AMOUNT_FIRST"


class StatementCreditStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# QuarterlyActivation status — PRD §3.2
# ---------------------------------------------------------------------------
class QuarterlyActivationStatus(str, Enum):
    ACTIVATED = "ACTIVATED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# PointsLedgerEntry enumerations — PRD §2.7
# ---------------------------------------------------------------------------
class LedgerEntryType(str, Enum):
    EARN = "EARN"
    EARN_ADJUST = "EARN_ADJUST"
    SIGNUP_BONUS = "SIGNUP_BONUS"
    TRANSFER_DEBIT = "TRANSFER_DEBIT"
    TRANSFER_REVERSE = "TRANSFER_REVERSE"
    REDEEM_DEBIT = "REDEEM_DEBIT"
    REDEEM_REVERSE = "REDEEM_REVERSE"
    EXPIRE = "EXPIRE"
    FORFEIT = "FORFEIT"


class LedgerSourceEntityType(str, Enum):
    TRANSACTION = "Transaction"
    POINTS_TRANSFER = "PointsTransfer"
    STATEMENT_CREDIT = "StatementCredit"
    ACCOUNT = "Account"
    SYSTEM = "System"


# ===========================================================================
# PRD §2.4 — Persisted entities carrying id + created_at + updated_at +
# version.
# ===========================================================================
class Cardholder(TypedDict, total=False):
    id: str
    email: str
    display_name: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    cardholder_id: str
    opened_at: str
    lifecycle_state: str
    spending_tier: str
    ytd_qualifying_spend_cents: int
    points_balance: int
    signup_bonus_state: str
    signup_bonus_qualifying_spend_cents: int
    signup_bonus_deadline_at: str
    last_qualifying_activity_at: str
    created_at: str
    updated_at: str
    version: int


class CashbackCategory(TypedDict, total=False):
    id: str
    code: str
    category_type: str
    base_rate_bps: int
    requires_activation: bool
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict, total=False):
    id: str
    account_id: str
    category_id: str
    txn_type: str
    amount_cents: int
    posted_at: str
    status: str
    points_provisional: int
    points_final: int
    created_at: str
    updated_at: str
    version: int


class TransferPartner(TypedDict, total=False):
    id: str
    code: str
    partner_type: str
    conversion_ratio_points_per_unit: int
    min_transfer_increment: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# PRD §2.4 — Append-only entities carrying ONLY id + created_at.
# No updated_at, no version.
# ===========================================================================
class QuarterlyActivation(TypedDict, total=False):
    id: str
    account_id: str
    category_id: str
    quarter_label: str
    activation_window_start: str
    activation_window_end: str
    activated_at: str
    status: str
    created_at: str


class PointsTransfer(TypedDict, total=False):
    id: str
    account_id: str
    partner_id: str
    requested_partner_units: int
    points_debited: int
    status: str
    initiated_at: str
    completed_at: Optional[str]
    created_at: str


class StatementCredit(TypedDict, total=False):
    id: str
    account_id: str
    redemption_mode: str
    requested_points: Optional[int]
    requested_amount_cents: Optional[int]
    points_debited: int
    credit_amount_cents: int
    applied_at: str
    status: str
    created_at: str


class PointsLedgerEntry(TypedDict, total=False):
    id: str
    account_id: str
    entry_type: str
    source_entity_type: str
    source_entity_id: Optional[str]
    delta_points: int
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "AccountLifecycleState",
    "SpendingTier",
    "SignupBonusState",
    "CategoryType",
    "TxnType",
    "TransactionStatus",
    "PartnerType",
    "PointsTransferStatus",
    "RedemptionMode",
    "StatementCreditStatus",
    "QuarterlyActivationStatus",
    "LedgerEntryType",
    "LedgerSourceEntityType",
    "Cardholder",
    "Account",
    "CashbackCategory",
    "Transaction",
    "TransferPartner",
    "QuarterlyActivation",
    "PointsTransfer",
    "StatementCredit",
    "PointsLedgerEntry",
]
