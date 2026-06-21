"""Domain types: entity TypedDicts, status enums, role enum.

Tow & Impound Lot Management API. Derived from the PRD entity model and lifecycles.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    LOT_OPERATOR = "LotOperator"
    POLICE_OFFICER = "PoliceOfficer"
    TOW_PROVIDER = "TowProvider"
    CLAIMANT = "Claimant"
    AUCTION_OFFICIAL = "AuctionOfficial"


# ─── Status enums ─────────────────────────────────────────────────────────────
class ImpoundLotStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class TowProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RotationAssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class TowOrderStatus(str, Enum):
    TOWED = "TOWED"
    STORED = "STORED"
    RELEASE_AUTHORIZED = "RELEASE_AUTHORIZED"
    RELEASED = "RELEASED"
    AUCTION_ELIGIBLE = "AUCTION_ELIGIBLE"
    AUCTIONED = "AUCTIONED"
    VOIDED = "VOIDED"


class HoldStatus(str, Enum):
    NONE = "NONE"
    POLICE_HOLD = "POLICE_HOLD"
    EVIDENCE_HOLD = "EVIDENCE_HOLD"


class TowType(str, Enum):
    POLICE = "POLICE"
    PRIVATE = "PRIVATE"
    ABANDONED = "ABANDONED"


class NotificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    DELIVERY_CONFIRMED = "DELIVERY_CONFIRMED"
    CERTIFIED_RETURNED = "CERTIFIED_RETURNED"
    UNDELIVERABLE = "UNDELIVERABLE"


class RecipientType(str, Enum):
    OWNER = "OWNER"
    LIENHOLDER = "LIENHOLDER"


class NotificationMethod(str, Enum):
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    PUBLICATION = "PUBLICATION"
    EMAIL = "EMAIL"


class InventoryCategory(str, Enum):
    PERSONAL_PROPERTY = "PERSONAL_PROPERTY"
    VEHICLE_DAMAGE = "VEHICLE_DAMAGE"
    EXTERIOR_PHOTO = "EXTERIOR_PHOTO"


class FeeWaiverReason(str, Enum):
    WRONGFUL_TOW = "WRONGFUL_TOW"
    HARDSHIP = "HARDSHIP"
    LAW_ENFORCEMENT_ERROR = "LAW_ENFORCEMENT_ERROR"
    BILLING_DISPUTE = "BILLING_DISPUTE"


class FeeWaiverStatus(str, Enum):
    REQUESTED = "REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class AuctionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class LedgerKind(str, Enum):
    ACCRUAL = "ACCRUAL"
    FREEZE = "FREEZE"
    RESUME = "RESUME"
    SETTLEMENT = "SETTLEMENT"


# ─── Entity TypedDicts ────────────────────────────────────────────────────────
# All primary entities carry id + created_at + updated_at + version,
# except StorageLedgerEntry which is immutable (id + created_at only).

class ImpoundLot(TypedDict):
    id: str
    name: str
    jurisdiction_code: str
    daily_storage_rate_cents: int
    admin_fee_cents: int
    lien_processing_fee_cents: int
    statutory_hold_days: int
    notice_grace_days: int
    max_provider_concurrent_offers: int
    rotation_cursor: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TowProvider(TypedDict):
    id: str
    company_name: str
    license_number: str
    rotation_rank: int
    offers_received_count: int
    offers_accepted_count: int
    trailing_window_size: int
    status: str
    raw_standing_pct: float
    effective_standing_pct: float
    created_at: str
    updated_at: str
    version: int


class Lienholder(TypedDict):
    id: str
    name: str
    mailing_address: str
    state_code: str
    created_at: str
    updated_at: str
    version: int


class RotationAssignment(TypedDict):
    id: str
    lot_id: str
    provider_id: str
    offered_at: str
    expires_at: str
    offer_ttl_minutes: int
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TowOrder(TypedDict):
    id: str
    lot_id: str
    provider_id: Optional[str]
    rotation_assignment_id: Optional[str]
    lienholder_id: Optional[str]
    auction_id: Optional[str]
    tow_type: str
    vin: str
    plate: str
    owner_name: str
    owner_address: str
    intake_at: str
    stored_at: Optional[str]
    accrual_frozen_at: Optional[str]
    accrued_days: int
    estimated_storage_cents: int
    accrued_storage_cents: int
    balance_due_cents: int
    waiver_credit_cents: int
    net_due_cents: int
    amount_paid_cents: int
    hold_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Notification(TypedDict):
    id: str
    tow_order_id: str
    recipient_type: str
    method: str
    sent_at: Optional[str]
    resolved_at: Optional[str]
    republished_from_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    tow_order_id: str
    category: str
    description: str
    photo_ref: str
    condition_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeWaiver(TypedDict):
    id: str
    tow_order_id: str
    reason: str
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    decided_by_user_id: Optional[str]
    filed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReleaseRecord(TypedDict):
    id: str
    tow_order_id: str
    amount_paid_cents: int
    released_to_name: str
    authorized_at: str
    created_at: str
    updated_at: str
    version: int


class Auction(TypedDict):
    id: str
    lot_id: str
    window_start: str
    window_end: str
    gross_proceeds_cents: int
    distributed_cents: int
    lien_payoff_cents: int
    surplus_to_owner_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# StorageLedgerEntry is immutable: carries ONLY id + created_at (no updated_at, no version).
class StorageLedgerEntry(TypedDict):
    id: str
    tow_order_id: str
    segment_start: str
    segment_end: Optional[str]
    days_counted: int
    segment_charge_cents: int
    kind: str
    created_at: str
