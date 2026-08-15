"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PUBLIC_USER = "PublicUser"
    CLAIMANT = "Claimant"
    INTAKE_OFFICER = "IntakeOfficer"
    PROPERTY_CUSTODIAN = "PropertyCustodian"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    RELEASE_OFFICER = "ReleaseOfficer"
    POLICE_LIAISON = "PoliceLiaison"
    AUCTION_COORDINATOR = "AuctionCoordinator"
    PROGRAM_ADMIN = "ProgramAdmin"


class ProgramType(str, Enum):
    TRANSIT = "TRANSIT"
    FACILITY = "FACILITY"


class ItemCategory(str, Enum):
    ELECTRONICS = "ELECTRONICS"
    JEWELRY = "JEWELRY"
    ID_DOCUMENT = "ID_DOCUMENT"
    KEYS = "KEYS"
    CLOTHING = "CLOTHING"
    BAG = "BAG"
    WALLET = "WALLET"
    BICYCLE = "BICYCLE"
    CASH = "CASH"
    OTHER = "OTHER"


class ValueTier(str, Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"


class DisposalMethod(str, Enum):
    AUCTION = "AUCTION"
    DESTRUCTION = "DESTRUCTION"
    DONATION = "DONATION"


class ItemStatus(str, Enum):
    STORED = "STORED"
    LISTED = "LISTED"
    RELEASE_PENDING = "RELEASE_PENDING"
    RELEASED = "RELEASED"
    REFERRED_TO_LE = "REFERRED_TO_LE"
    IN_LE_CUSTODY = "IN_LE_CUSTODY"
    EVIDENCE = "EVIDENCE"
    AUCTION_ELIGIBLE = "AUCTION_ELIGIBLE"
    LOTTED = "LOTTED"
    SOLD = "SOLD"
    DISPOSAL_PENDING = "DISPOSAL_PENDING"
    DISPOSED = "DISPOSED"
    DONATED = "DONATED"


ITEM_TERMINAL_STATES = {"RELEASED", "EVIDENCE", "SOLD", "DISPOSED", "DONATED"}

OCCUPYING_STATES = {
    "STORED", "LISTED", "RELEASE_PENDING", "REFERRED_TO_LE",
    "AUCTION_ELIGIBLE", "LOTTED", "DISPOSAL_PENDING",
}


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    STAYED = "STAYED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    RELEASED = "RELEASED"


class ReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    IN_CUSTODY = "IN_CUSTODY"
    RETURNED = "RETURNED"
    CONVERTED_TO_EVIDENCE = "CONVERTED_TO_EVIDENCE"


class InquiryStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"


class AuctionEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AuctionLotStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SOLD = "SOLD"
    CLOSED_UNSOLD = "CLOSED_UNSOLD"
    CANCELLED = "CANCELLED"


class ProofDescriptionDetail(str, Enum):
    BRIEF = "BRIEF"
    DETAILED = "DETAILED"


class HandoverMethod(str, Enum):
    IN_PERSON = "IN_PERSON"
    MAIL = "MAIL"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id, created_at, updated_at, version (PRD §2.4).

class Program(TypedDict):
    id: str
    name: str
    program_type: str
    contact_email: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class RetentionPolicy(TypedDict):
    id: str
    program_id: str
    item_category: str
    value_tier: str
    retention_days: int
    disposal_method: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class StorageLocation(TypedDict):
    id: str
    program_id: str
    name: str
    capacity_slots: int
    supports_high_value: bool
    active: bool
    occupied_slots: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    program_id: str
    name: str
    address: str
    insurance_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Claimant(TypedDict):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    id_verified: bool
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    program_id: str
    storage_location_id: str
    category: str
    declared_value_cents: int
    value_tier: str
    is_identification: bool
    description: str
    found_at: str
    found_location: str
    external_ref: Optional[str]
    retention_policy_id: str
    retention_deadline: str
    status: str
    unsold_count: int
    pending_disposal_method: Optional[str]
    intake_officer_id: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    item_id: str
    claimant_id: str
    status: str
    proof_serial: bool
    proof_photo: bool
    proof_receipt: bool
    proof_description_detail: str
    proof_score: int
    examiner_id: Optional[str]
    decision_reason: Optional[str]
    pre_stay_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inquiry(TypedDict):
    id: str
    item_id: Optional[str]
    program_id: Optional[str]
    contact_email: str
    subject: str
    message: str
    status: str
    sla_deadline: str
    answer_text: Optional[str]
    answered_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuctionEvent(TypedDict):
    id: str
    venue_id: str
    program_id: str
    name: str
    starts_at: str
    ends_at: str
    status: str
    gross_proceeds_cents: Optional[int]
    total_commission_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AuctionLot(TypedDict):
    id: str
    event_id: str
    title: str
    status: str
    minimum_bid_cents: int
    hammer_price_cents: Optional[int]
    created_by: str
    finalized_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only membership row: carries ONLY id + created_at among the common
# fields; updated_at and version are absent (PRD §2.4).
class LotItem(TypedDict):
    id: str
    lot_id: str
    item_id: str
    floor_price_cents: int
    created_at: str


class ReferralCase(TypedDict):
    id: str
    item_id: str
    agency_name: str
    case_number: str
    status: str
    referred_by: str
    created_at: str
    updated_at: str
    version: int


# Append-only release documentation: carries ONLY id + created_at among the
# common fields; updated_at and version are absent (PRD §2.4).
class ReleaseRecord(TypedDict):
    id: str
    item_id: str
    claim_id: str
    released_by: str
    handover_method: str
    id_document_ref: str
    released_at: str
    created_at: str
