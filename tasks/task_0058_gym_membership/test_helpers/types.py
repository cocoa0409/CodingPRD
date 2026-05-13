"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Per PRD §2.4 each entity has one of two
shapes:

- Versioned (id + created_at + updated_at + version): Member, CardType, Card,
  Trainer, TrainerSlot, PTBooking, PTPackage, GroupClass, GroupBooking,
  FreezeEpisode.

- Append-only (id + created_at ONLY; NO updated_at, NO version):
  WalletTransaction, TransferRecord, CommissionRecord, PayoutCycle,
  RenewalReminder, AuditLogEntry.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STAFF_OPS = "StaffOps"
    MEMBER = "Member"
    TRAINER = "Trainer"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.x)
# ---------------------------------------------------------------------------
class CardTypeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CardCategory(str, Enum):
    PER_VISIT = "PER_VISIT"
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class CardStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    EXPIRED = "EXPIRED"
    REFUNDED = "REFUNDED"
    TRANSFERRED = "TRANSFERRED"


class FreezeEpisodeStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"


class FreezeReason(str, Enum):
    ILLNESS = "ILLNESS"
    BUSINESS_TRIP = "BUSINESS_TRIP"


class TrainerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TrainerTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class TrainerSlotStatus(str, Enum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    NO_SHOW = "NO_SHOW"


class PTBookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    NO_SHOW = "NO_SHOW"


class PTBookingMode(str, Enum):
    SINGLE = "SINGLE"
    PACKAGE = "PACKAGE"


class PTPackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    REFUNDED = "REFUNDED"


class GroupClassStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELED = "CANCELED"
    COMPLETED = "COMPLETED"


class GroupBookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELED = "CANCELED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class WalletTxnKind(str, Enum):
    RECHARGE = "RECHARGE"
    BONUS_GRANT = "BONUS_GRANT"
    DEBIT = "DEBIT"
    REFUND = "REFUND"
    BONUS_EXPIRE = "BONUS_EXPIRE"
    ADJUSTMENT = "ADJUSTMENT"


class WalletTxnBucket(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    BONUS = "BONUS"


class WalletServiceType(str, Enum):
    PT_SESSION = "PT_SESSION"
    GROUP_CLASS = "GROUP_CLASS"
    CARD_ISSUANCE = "CARD_ISSUANCE"
    TRANSFER_FEE = "TRANSFER_FEE"


class CommissionKind(str, Enum):
    SESSION = "SESSION"
    PACKAGE_SALE = "PACKAGE_SALE"
    TIER_BONUS = "TIER_BONUS"
    REVERSAL = "REVERSAL"


class PayoutCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReminderTier(str, Enum):
    T30 = "T30"
    T7 = "T7"
    T0 = "T0"


class ReminderStatus(str, Enum):
    SENT = "SENT"
    AUTO_RENEW_TRIGGERED = "AUTO_RENEW_TRIGGERED"
    LAPSED = "LAPSED"


class AuditAction(str, Enum):
    CARD_ADJUST = "CARD_ADJUST"
    COMMISSION_ADJUST = "COMMISSION_ADJUST"
    CARD_REFUND = "CARD_REFUND"
    FREEZE_OVERRIDE = "FREEZE_OVERRIDE"
    COMMISSION_REVERSAL = "COMMISSION_REVERSAL"


# ---------------------------------------------------------------------------
# Versioned TypedDicts (PRD §2.4: id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Member(TypedDict, total=False):
    id: str
    full_name: str
    phone: str
    email: str
    family_group_id: Optional[str]
    notification_channels: List[str]
    auto_renew_authorized: bool
    wallet_balance_cents: int
    bonus_balance_cents: int
    bonus_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CardType(TypedDict, total=False):
    id: str
    code: str
    category: str
    price_cents: int
    validity_days: int
    visit_quota: int
    family_shareable: bool
    max_freeze_days: int
    transfer_fee_pct_bp: int
    renewal_discount_pct_bp: int
    refund_eligibility_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Card(TypedDict, total=False):
    id: str
    card_type_id: str
    holder_member_id: str
    issuance_price_cents: int
    activation_date: Optional[str]
    original_expiry_date: Optional[str]
    effective_expiry_date: Optional[str]
    visits_consumed: int
    visits_remaining: Optional[int]
    cumulative_freeze_days: int
    status: str
    parent_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Trainer(TypedDict, total=False):
    id: str
    full_name: str
    specialties: List[str]
    session_commission_pct_bp: int
    package_commission_pct_bp: int
    tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainerSlot(TypedDict, total=False):
    id: str
    trainer_id: str
    starts_at: str
    ends_at: str
    specialty_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PTBooking(TypedDict, total=False):
    id: str
    member_id: str
    trainer_id: str
    slot_id: str
    package_id: Optional[str]
    billing_mode: str
    session_price_cents: int
    status: str
    scheduled_starts_at: str
    created_at: str
    updated_at: str
    version: int


class PTPackage(TypedDict, total=False):
    id: str
    member_id: str
    trainer_id: str
    total_sessions: int
    gross_price_cents: int
    sessions_consumed: int
    sessions_refunded: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GroupClass(TypedDict, total=False):
    id: str
    class_code: str
    instructor_trainer_id: str
    substitute_trainer_id: Optional[str]
    starts_at: str
    ends_at: str
    capacity: int
    recurrence_series_id: Optional[str]
    deduction_cents: int
    status: str
    confirmed_count: int
    waitlist_count: int
    created_at: str
    updated_at: str
    version: int


class GroupBooking(TypedDict, total=False):
    id: str
    class_id: str
    member_id: str
    card_id: Optional[str]
    status: str
    waitlist_position: Optional[int]
    waitlisted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FreezeEpisode(TypedDict, total=False):
    id: str
    card_id: str
    reason: str
    requested_days: int
    actual_days: int
    starts_at: Optional[str]
    ends_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only TypedDicts (PRD §2.4: id + created_at ONLY)
# ---------------------------------------------------------------------------
class WalletTransaction(TypedDict, total=False):
    id: str
    member_id: str
    kind: str
    amount_cents: int
    bucket: str
    service_type: Optional[str]
    ref_entity: str
    expires_at: Optional[str]
    created_at: str


class TransferRecord(TypedDict, total=False):
    id: str
    source_card_id: str
    destination_card_id: str
    from_member_id: str
    to_member_id: str
    remaining_value_cents: int
    transfer_fee_cents: int
    created_at: str


class CommissionRecord(TypedDict, total=False):
    id: str
    trainer_id: str
    kind: str
    amount_cents: int
    ref_entity: str
    payout_cycle_id: Optional[str]
    created_at: str


class PayoutCycle(TypedDict, total=False):
    id: str
    cycle_start: str
    cycle_end: str
    closed_at: Optional[str]
    status: str
    created_at: str


class RenewalReminder(TypedDict, total=False):
    id: str
    card_id: str
    tier: str
    channels_dispatched: List[str]
    status: str
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    action: str
    target_entity: str
    payload: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "CardTypeStatus", "CardCategory", "CardStatus",
    "FreezeEpisodeStatus", "FreezeReason",
    "TrainerStatus", "TrainerTier", "TrainerSlotStatus",
    "PTBookingStatus", "PTBookingMode", "PTPackageStatus",
    "GroupClassStatus", "GroupBookingStatus",
    "WalletTxnKind", "WalletTxnBucket", "WalletServiceType",
    "CommissionKind", "PayoutCycleStatus",
    "ReminderTier", "ReminderStatus", "AuditAction",
    "Member", "CardType", "Card", "Trainer", "TrainerSlot",
    "PTBooking", "PTPackage", "GroupClass", "GroupBooking",
    "FreezeEpisode",
    "WalletTransaction", "TransferRecord", "CommissionRecord",
    "PayoutCycle", "RenewalReminder", "AuditLogEntry",
]
