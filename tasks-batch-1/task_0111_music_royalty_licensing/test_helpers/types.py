"""Domain types: entity TypedDicts, status enums, role enum.

All field names match the PRD exactly. Entities carrying the full common-field
set (id, created_at, updated_at, version) are distinguished from the lone
append-only audit row (LedgerEntry: id + created_at only).
"""
from enum import Enum
from typing import TypedDict


# --- Roles (PRD §2.1) ---

class UserRole(str, Enum):
    ADMINISTRATOR = "Administrator"
    ROYALTY_OPERATOR = "RoyaltyOperator"
    LICENSEE = "Licensee"
    RIGHTSHOLDER = "Rightsholder"


# --- Enums ---

class PartyType(str, Enum):
    WRITER = "WRITER"
    PUBLISHER = "PUBLISHER"
    LABEL = "LABEL"


class RightsholderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProAffiliation(str, Enum):
    ASCAP = "ASCAP"
    BMI = "BMI"
    NONE = "NONE"


class ShareRole(str, Enum):
    WRITER = "WRITER"
    PUBLISHER = "PUBLISHER"


class ReleaseType(str, Enum):
    STREAMING = "STREAMING"
    PHYSICAL = "PHYSICAL"


class RightsType(str, Enum):
    SYNC = "SYNC"
    MECHANICAL = "MECHANICAL"
    PERFORMANCE = "PERFORMANCE"


class RightsWindowStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class UsageType(str, Enum):
    PERFORMANCE = "PERFORMANCE"
    MECHANICAL = "MECHANICAL"


class UsageEventStatus(str, Enum):
    INGESTED = "INGESTED"
    ALLOCATED = "ALLOCATED"
    VOIDED = "VOIDED"


class MediaType(str, Enum):
    FILM = "FILM"
    TV = "TV"
    AD = "AD"
    GAME = "GAME"


class SyncLicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    EXECUTED = "EXECUTED"
    DECLINED = "DECLINED"


class AdvanceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECOUPED = "RECOUPED"
    WRITTEN_OFF = "WRITTEN_OFF"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"


class LedgerEntryType(str, Enum):
    EARNING = "EARNING"
    RECOUPMENT = "RECOUPMENT"
    WITHHOLDING = "WITHHOLDING"


class LedgerSourceType(str, Enum):
    USAGE_EVENT = "USAGE_EVENT"
    SYNC_LICENSE = "SYNC_LICENSE"
    ADVANCE = "ADVANCE"
    STATEMENT = "STATEMENT"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


# --- Entities carrying the full common-field set (id/created_at/updated_at/version) ---

class Rightsholder(TypedDict):
    id: str
    legal_name: str
    party_type: str
    payee_country: str
    minimum_payout_cents: int
    withholding_pct: float
    lifetime_earned_cents: int
    unrecouped_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Work(TypedDict):
    id: str
    title: str
    iswc: str
    pro_affiliation: str
    duration_seconds: int
    shares_locked: bool
    split_total_bps: int
    created_at: str
    updated_at: str
    version: int


class CompositionShare(TypedDict):
    id: str
    work_id: str
    rightsholder_id: str
    role: str
    split_bps: int
    created_at: str
    updated_at: str
    version: int


class Recording(TypedDict):
    id: str
    work_id: str
    isrc: str
    title: str
    release_type: str
    duration_seconds: int
    shares_locked: bool
    split_total_bps: int
    created_at: str
    updated_at: str
    version: int


class RecordingShare(TypedDict):
    id: str
    recording_id: str
    rightsholder_id: str
    split_bps: int
    created_at: str
    updated_at: str
    version: int


class RightsWindow(TypedDict):
    id: str
    recording_id: str
    territory: str
    rights_type: str
    term_start: str
    term_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UsageEvent(TypedDict):
    id: str
    recording_id: str
    usage_type: str
    territory: str
    occurred_at: str
    quantity: int
    gross_revenue_cents: int
    status: str
    royalty_cents: int
    allocated_holder_count: int
    created_at: str
    updated_at: str
    version: int


class SyncLicense(TypedDict):
    id: str
    recording_id: str
    licensee_id: str
    media_type: str
    territory: str
    term_months: int
    base_fee_cents: int
    quoted_fee_cents: int
    status: str
    counter_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Advance(TypedDict):
    id: str
    rightsholder_id: str
    principal_cents: int
    recoupment_pct: float
    recouped_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict):
    id: str
    rightsholder_id: str
    period_start: str
    period_end: str
    gross_earnings_cents: int
    recoupment_applied_cents: int
    withholding_cents: int
    net_payable_cents: int
    carried_forward_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    statement_id: str
    rightsholder_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only audit row: id + created_at ONLY (no updated_at, no version) ---

class LedgerEntry(TypedDict):
    id: str
    statement_id: str
    rightsholder_id: str
    entry_type: str
    source_type: str
    source_id: str
    amount_cents: int
    created_at: str
