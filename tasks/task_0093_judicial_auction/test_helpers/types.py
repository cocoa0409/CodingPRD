"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4 most entities (Lot, BidderAccount, Auction, Deposit,
Confirmation, Payment, TransferOrder) carry id/created_at/updated_at/
version. Bid and AuditEvent are append-only — they carry only id and
created_at; no updated_at, no version on those entities.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    COURT_CLERK = "CourtClerk"
    AUCTION_ADMIN = "AuctionAdmin"
    BIDDER = "Bidder"
    OBSERVER = "Observer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class LotStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTERED = "REGISTERED"
    ANNOUNCED = "ANNOUNCED"
    AUCTIONED = "AUCTIONED"
    WITHDRAWN = "WITHDRAWN"
    TRANSFERRED = "TRANSFERRED"


class AssetProfile(str, Enum):
    REAL_ESTATE = "REAL_ESTATE"
    VEHICLE = "VEHICLE"
    EQUITY = "EQUITY"
    MOVABLE_ASSET = "MOVABLE_ASSET"


class EncumbranceKind(str, Enum):
    MORTGAGE = "MORTGAGE"
    LIEN = "LIEN"
    TENANCY = "TENANCY"


class BidderAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"


class AuctionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    SOLD = "SOLD"
    UNSOLD = "UNSOLD"
    CANCELLED = "CANCELLED"


class DepositMode(str, Enum):
    FIXED = "FIXED"
    PERCENT = "PERCENT"


class BidValidity(str, Enum):
    VALID = "VALID"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class DepositStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"
    DISPUTED = "DISPUTED"


class ConfirmationStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SEALED = "SEALED"
    FAILED = "FAILED"


class FailureReason(str, Enum):
    COLLUSION_FOUND = "COLLUSION_FOUND"
    BIDDER_DISQUALIFIED = "BIDDER_DISQUALIFIED"
    COURT_OVERRIDE = "COURT_OVERRIDE"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    FORFEITED = "FORFEITED"


class TransferOrderStatus(str, Enum):
    INITIATED = "INITIATED"
    AGENCY_NOTIFIED = "AGENCY_NOTIFIED"
    HANDOVER_DONE = "HANDOVER_DONE"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


class CounterpartAgency(str, Enum):
    REAL_ESTATE_REGISTRY = "REAL_ESTATE_REGISTRY"
    VEHICLE_AUTHORITY = "VEHICLE_AUTHORITY"
    EQUITY_REGISTRY = "EQUITY_REGISTRY"
    COURT_BAILIFF = "COURT_BAILIFF"


class AuditEventKind(str, Enum):
    BID_PLACED = "BID_PLACED"
    BID_REJECTED = "BID_REJECTED"
    BID_ROLLED_BACK = "BID_ROLLED_BACK"
    SOFT_CLOSE_EXTENSION = "SOFT_CLOSE_EXTENSION"
    AUCTION_CLOSED = "AUCTION_CLOSED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    DEPOSIT_REFUNDED = "DEPOSIT_REFUNDED"
    DEPOSIT_FORFEITED = "DEPOSIT_FORFEITED"
    CONFIRMATION_ISSUED = "CONFIRMATION_ISSUED"
    CONFIRMATION_SEALED = "CONFIRMATION_SEALED"
    CONFIRMATION_FAILED = "CONFIRMATION_FAILED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    PAYMENT_OVERDUE = "PAYMENT_OVERDUE"
    TRANSFER_NOTIFIED = "TRANSFER_NOTIFIED"
    TRANSFER_COMPLETED = "TRANSFER_COMPLETED"
    COLLUSION_FLAGGED = "COLLUSION_FLAGGED"
    REAUCTION_TRIGGERED = "REAUCTION_TRIGGERED"
    SYSTEM_FAULT_ROLLBACK = "SYSTEM_FAULT_ROLLBACK"


# ---------------------------------------------------------------------------
# Mutable-resource entities (PRD §2.4: id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Lot(TypedDict, total=False):
    id: str
    court_order_no: str
    asset_profile: str
    assessment_value_cents: int
    assessment_report_uri: str
    encumbrances: List[dict]
    status: str
    announcement_published_at: Optional[str]
    auction_scheduled_start_at: str
    inspection_window_start_at: str
    inspection_window_end_at: str
    round_number: int
    created_at: str
    updated_at: str
    version: int


class BidderAccount(TypedDict, total=False):
    id: str
    real_name: str
    id_document_no: str
    ip_fingerprint: Optional[str]
    account_age_days: int
    status: str
    collusion_risk_score: int
    created_at: str
    updated_at: str
    version: int


class Auction(TypedDict, total=False):
    id: str
    lot_id: str
    starting_price_cents: int
    bid_increment_cents: int
    bid_cap_cents: Optional[int]
    deposit_mode: str
    deposit_fixed_cents: Optional[int]
    deposit_percent_bps: Optional[int]
    deposit_amount_cents: int
    deposit_deadline_at: str
    payment_deadline_days: int
    scheduled_start_at: str
    scheduled_end_at: str
    effective_end_at: str
    soft_close_window_seconds: int
    soft_close_extension_seconds: int
    current_high_cents: Optional[int]
    highest_bid_id: Optional[str]
    second_highest_bid_id: Optional[str]
    status: str
    outcome_winner_account_id: Optional[str]
    round_number: int
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict, total=False):
    id: str
    auction_id: str
    bidder_account_id: str
    amount_cents: int
    status: str
    paid_at: Optional[str]
    refunded_at: Optional[str]
    refund_due_at: Optional[str]
    dispute_opened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Confirmation(TypedDict, total=False):
    id: str
    auction_id: str
    winning_bid_id: str
    ruling_document_uri: str
    status: str
    issued_at: Optional[str]
    sealed_at: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    confirmation_id: str
    balance_due_cents: int
    penalty_accrued_cents: int
    amount_paid_cents: int
    status: str
    due_at: str
    receipt_no: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferOrder(TypedDict, total=False):
    id: str
    confirmation_id: str
    counterpart_agency: str
    handover_scheduled_at: str
    transfer_instrument_uri: str
    tenancy_cleared: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (PRD §2.4: id + created_at only, no updated_at/version)
# ---------------------------------------------------------------------------
class Bid(TypedDict, total=False):
    id: str
    created_at: str
    auction_id: str
    bidder_account_id: Optional[str]  # masked for non-CourtClerk callers
    amount_cents: int
    client_seq_no: int
    validity: str
    masked_handle: str


class AuditEvent(TypedDict, total=False):
    id: str
    created_at: str
    kind: str
    actor_role: str
    actor_id: str
    subject_entity: str
    subject_id: str
    payload: dict


__all__ = [
    "UserRole",
    "LotStatus",
    "AssetProfile",
    "EncumbranceKind",
    "BidderAccountStatus",
    "AuctionStatus",
    "DepositMode",
    "BidValidity",
    "DepositStatus",
    "ConfirmationStatus",
    "FailureReason",
    "PaymentStatus",
    "TransferOrderStatus",
    "CounterpartAgency",
    "AuditEventKind",
    "Lot",
    "BidderAccount",
    "Auction",
    "Deposit",
    "Confirmation",
    "Payment",
    "TransferOrder",
    "Bid",
    "AuditEvent",
]
