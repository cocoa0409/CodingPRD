"""Domain types: entity TypedDicts, status enums, role enum.

Field names and structures follow the PRD's Gift Card & Stored-Value Program contract.
LedgerEntry and RedemptionLeg are immutable audit records (id + created_at only) — they
carry no updated_at and no version.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Status enums ─────────────────────────────────────────────────────────

class GiftCardLifecycleStatus(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class GiftCardRiskStatus(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"
    FROZEN_RISK = "FROZEN_RISK"


class LedgerEntryType(str, Enum):
    LOAD = "LOAD"
    RELOAD = "RELOAD"
    BONUS = "BONUS"
    REDEEM = "REDEEM"
    REFUND = "REFUND"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    DORMANCY_FEE = "DORMANCY_FEE"
    BREAKAGE = "BREAKAGE"
    ESCHEAT = "ESCHEAT"
    REVERSAL = "REVERSAL"


class LedgerEntryStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class AuthorizationHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CAPTURED = "CAPTURED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class RedemptionStatus(str, Enum):
    DRAFT = "DRAFT"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class BulkOrderStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    ACTIVATED = "ACTIVATED"
    CANCELLED = "CANCELLED"


class ReplacementRequestStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RefundRequestStatus(str, Enum):
    PENDING = "PENDING"
    NEEDS_REVISION = "NEEDS_REVISION"
    APPLIED = "APPLIED"
    DENIED = "DENIED"


class DormancyWaiverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PromoCampaignStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class FormFactor(str, Enum):
    DIGITAL = "DIGITAL"
    PHYSICAL = "PHYSICAL"


class BreakagePolicy(str, Enum):
    RECOGNIZE = "RECOGNIZE"
    ESCHEAT = "ESCHEAT"


class ReplacementReason(str, Enum):
    FRAUD = "FRAUD"
    LOST = "LOST"
    DAMAGED = "DAMAGED"


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    STORE_ASSOCIATE = "StoreAssociate"
    CUSTOMER = "Customer"
    FRAUD_ANALYST = "FraudAnalyst"
    B2B_BUYER = "B2BBuyer"


# ─── Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ─

class Program(TypedDict):
    id: str
    name: str
    default_currency: str
    reload_min_cents: int
    reload_max_balance_cents: int
    hold_ttl_seconds: int
    b2b_discount_pct: float
    outstanding_liability_cents: int
    breakage_recognized_cents: int
    escheat_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class StateRule(TypedDict):
    id: str
    program_id: str
    state_code: str
    expiration_allowed: bool
    dormancy_fee_allowed: bool
    breakage_policy: str
    escheat_rate: float
    dormancy_threshold_months: int
    created_at: str
    updated_at: str
    version: int


class PromoCampaign(TypedDict):
    id: str
    program_id: str
    name: str
    bonus_pct: float
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    residence_state_code: str
    is_corporate: bool
    created_at: str
    updated_at: str
    version: int


class GiftCard(TypedDict):
    id: str
    program_id: str
    owner_customer_id: Optional[str]
    form_factor: str
    state_code: str
    lifecycle_status: str
    risk_status: str
    settled_balance_cents: int
    pending_hold_cents: int
    available_balance_cents: int
    last_activity_at: str
    replaced_by_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuthorizationHold(TypedDict):
    id: str
    card_id: str
    amount_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Redemption(TypedDict):
    id: str
    program_id: str
    customer_id: Optional[str]
    requested_amount_cents: int
    card_id_order: List[str]
    allocated_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BulkOrder(TypedDict):
    id: str
    program_id: str
    buyer_customer_id: str
    card_count: int
    face_value_cents: int
    state_code: str
    net_invoice_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplacementRequest(TypedDict):
    id: str
    old_card_id: str
    new_card_id: Optional[str]
    reason: str
    transferred_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict):
    id: str
    card_id: str
    redemption_id: Optional[str]
    requested_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DormancyWaiver(TypedDict):
    id: str
    card_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only audit records (common_fields: false → id/created_at only) ────

class LedgerEntry(TypedDict):
    id: str
    card_id: str
    program_id: str
    entry_type: str
    amount_cents: int
    status: str
    source_ref_id: Optional[str]
    reverses_entry_id: Optional[str]
    created_at: str


class RedemptionLeg(TypedDict):
    id: str
    redemption_id: str
    card_id: str
    leg_amount_cents: int
    ledger_entry_id: Optional[str]
    created_at: str
