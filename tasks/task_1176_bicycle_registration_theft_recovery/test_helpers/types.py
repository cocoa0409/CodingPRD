"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    OWNER = "Owner"
    PARTNER = "Partner"
    REGISTRAR = "Registrar"
    ADMIN = "Admin"


class PartnerOrgStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class OrgType(str, Enum):
    LAW_ENFORCEMENT = "LAW_ENFORCEMENT"
    BIKE_SHOP = "BIKE_SHOP"
    CAMPUS = "CAMPUS"


class RegistryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    STOLEN = "STOLEN"
    RECOVERED = "RECOVERED"
    RETURNED = "RETURNED"


class IntegrityStatus(str, Enum):
    CLEAR = "CLEAR"
    DUPLICATE_SUSPECT = "DUPLICATE_SUSPECT"
    MERGED = "MERGED"


class TransferStatus(str, Enum):
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TheftReportStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED_RECOVERED = "CLOSED_RECOVERED"


class IntakeStatus(str, Enum):
    INTAKE = "INTAKE"
    CLAIM_PENDING = "CLAIM_PENDING"
    RETURNED = "RETURNED"
    UNCLAIMED = "UNCLAIMED"
    DISPOSITION_SCHEDULED = "DISPOSITION_SCHEDULED"
    DISPOSED = "DISPOSED"


class MatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    NOTIFIED = "NOTIFIED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AuctionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUTBID = "OUTBID"
    WINNING = "WINNING"
    WON = "WON"
    LOST = "LOST"
    RETRACTED = "RETRACTED"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventRegistrationStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class DuplicateFlagStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class LedgerEntryType(str, Enum):
    REGISTRATION_FEE = "REGISTRATION_FEE"
    FEE_WAIVER = "FEE_WAIVER"
    TRANSFER_FEE = "TRANSFER_FEE"
    STORAGE_FEE = "STORAGE_FEE"
    AUCTION_COMMISSION = "AUCTION_COMMISSION"
    AUCTION_PARTNER_PAYOUT = "AUCTION_PARTNER_PAYOUT"
    AUCTION_ESCROW = "AUCTION_ESCROW"
    REVERSAL = "REVERSAL"


class LedgerDirection(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerAccount(str, Enum):
    OWNER = "OWNER"
    PARTNER_ORG = "PARTNER_ORG"
    PROGRAM = "PROGRAM"
    ESCROW = "ESCROW"


class NotificationKind(str, Enum):
    MATCH_FOUND = "MATCH_FOUND"
    CLAIM_APPROVED = "CLAIM_APPROVED"
    CLAIM_REJECTED = "CLAIM_REJECTED"
    TRANSFER_COMPLETED = "TRANSFER_COMPLETED"
    TRANSFER_CANCELLED_STOLEN = "TRANSFER_CANCELLED_STOLEN"
    REPORT_FLAGGED = "REPORT_FLAGGED"
    BID_OUTBID = "BID_OUTBID"
    AUCTION_WON = "AUCTION_WON"


# --- Entity TypedDicts -------------------------------------------------------
# All primary resources carry id + created_at + updated_at + version (PRD §2.5).
# LedgerEntry is the deliberate exception: append-only, id + created_at only.


class Owner(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    phone: Optional[str]
    bikes_registered_count: int
    created_at: str
    updated_at: str
    version: int


class PartnerOrg(TypedDict, total=False):
    id: str
    name: str
    org_type: str
    jurisdiction_code: str
    contact_email: str
    status: str
    total_recoveries_count: int
    storage_fees_earned_cents: int
    created_at: str
    updated_at: str
    version: int


class Bicycle(TypedDict, total=False):
    id: str
    serial_number: str
    serial_normalized: str
    manufacturer: str
    model: str
    primary_color: str
    declared_value_cents: int
    photo_url: str
    photo_hash: Optional[str]
    registration_fee_cents: int
    waiver_code_used: Optional[str]
    current_owner_id: str
    registry_status: str
    integrity_status: str
    created_at: str
    updated_at: str
    version: int


class OwnershipTransfer(TypedDict, total=False):
    id: str
    bicycle_id: str
    from_owner_id: str
    to_owner_id: str
    to_owner_email: str
    sale_price_cents: int
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class TheftReport(TypedDict, total=False):
    id: str
    bicycle_id: str
    owner_id: str
    occurred_at: str
    theft_location: str
    police_case_number: Optional[str]
    description: Optional[str]
    status: str
    info_request_text: Optional[str]
    response_text: Optional[str]
    flagged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecoveryIntake(TypedDict, total=False):
    id: str
    partner_org_id: str
    serial_number_raw: str
    serial_normalized: str
    manufacturer: Optional[str]
    model: Optional[str]
    primary_color: str
    photo_url: Optional[str]
    photo_hash: Optional[str]
    found_at: str
    found_location: str
    appraised_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MatchCandidate(TypedDict, total=False):
    id: str
    recovery_intake_id: str
    theft_report_id: str
    bicycle_id: str
    screening_score: int
    forensic_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OwnerClaim(TypedDict, total=False):
    id: str
    recovery_intake_id: str
    match_id: str
    owner_id: str
    proof_text: str
    status: str
    reason_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Auction(TypedDict, total=False):
    id: str
    recovery_intake_id: str
    starts_at: str
    ends_at: str
    reserve_price_cents: int
    estimated_storage_fee_cents: int
    estimated_program_commission_cents: int
    estimated_partner_payout_cents: int
    final_storage_fee_cents: Optional[int]
    final_program_commission_cents: Optional[int]
    final_partner_payout_cents: Optional[int]
    winning_bid_id: Optional[str]
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    auction_id: str
    bidder_owner_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RegistryEvent(TypedDict, total=False):
    id: str
    host_org_id: str
    title: str
    venue: str
    starts_at: str
    ends_at: str
    capacity: int
    registered_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict, total=False):
    id: str
    event_id: str
    owner_id: str
    status: str
    waiver_code: str
    waiver_used: bool
    created_at: str
    updated_at: str
    version: int


class DuplicateFlag(TypedDict, total=False):
    id: str
    bicycle_a_id: str
    bicycle_b_id: str
    confidence_score: int
    status: str
    merged_into_bicycle_id: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    # Append-only (PRD §2.5): carries ONLY id + created_at of the common set —
    # NO updated_at, NO version.
    id: str
    entry_type: str
    direction: str
    account: str
    amount_cents: int
    owner_id: Optional[str]
    partner_org_id: Optional[str]
    auction_id: Optional[str]
    bicycle_id: Optional[str]
    reference_note: Optional[str]
    created_at: str


class Notification(TypedDict, total=False):
    id: str
    owner_id: str
    kind: str
    message: str
    related_entity_type: Optional[str]
    related_entity_id: Optional[str]
    read: bool
    created_at: str
    updated_at: str
    version: int
