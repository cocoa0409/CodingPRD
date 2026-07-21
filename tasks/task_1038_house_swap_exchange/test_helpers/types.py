"""Domain types: entity TypedDicts, status enums, role enum.

Field membership follows the PRD: most resources carry the common lifecycle
fields (id, created_at, updated_at, version); a PointsLedgerEntry is append-only
and carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status enums ------------------------------------------------------------
class MemberVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class MembershipTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class MembershipStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class HomeListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class AvailabilityWindowStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"


class VerificationType(str, Enum):
    IDENTITY = "IDENTITY"
    HOME = "HOME"


class VerificationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ExchangeType(str, Enum):
    POINTS = "POINTS"
    RECIPROCAL = "RECIPROCAL"


class ExchangeRequestStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ExchangeAgreementStatus(str, Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InsuranceStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    CLAIMED = "CLAIMED"


class LedgerEntryType(str, Enum):
    WELCOME_BONUS = "WELCOME_BONUS"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"
    EXCHANGE_HOLD = "EXCHANGE_HOLD"
    EXCHANGE_DEBIT = "EXCHANGE_DEBIT"
    EXCHANGE_CREDIT = "EXCHANGE_CREDIT"
    EXCHANGE_REFUND = "EXCHANGE_REFUND"
    CREDIT_REVERSAL = "CREDIT_REVERSAL"
    DAMAGE_SETTLEMENT = "DAMAGE_SETTLEMENT"
    DISPUTE_PENALTY = "DISPUTE_PENALTY"


class LedgerEntryStatus(str, Enum):
    HELD = "HELD"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class DamageClaimStatus(str, Enum):
    FILED = "FILED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_FOR_CLAIMANT = "RESOLVED_FOR_CLAIMANT"
    RESOLVED_FOR_RESPONDENT = "RESOLVED_FOR_RESPONDENT"
    WITHDRAWN = "WITHDRAWN"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version)
class Member(TypedDict):
    id: str
    email: str
    full_name: str
    home_city: str
    verification_status: str
    active_membership_tier: Optional[str]
    settled_points_balance: int
    available_points_balance: int
    trust_score: int
    completed_exchange_count: int
    upheld_damage_count: int
    disputes_lost_count: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    tier: str
    status: str
    activated_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HomeListing(TypedDict):
    id: str
    owner_member_id: str
    title: str
    address_city: str
    address_country: str
    points_per_night: int
    max_points_per_exchange: int
    min_trust_score: int
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AvailabilityWindow(TypedDict):
    id: str
    listing_id: str
    start_date: str
    end_date: str
    nights: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Verification(TypedDict):
    id: str
    member_id: str
    verification_type: str
    document_ref: str
    status: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExchangeRequest(TypedDict):
    id: str
    requester_member_id: str
    target_listing_id: str
    offered_listing_id: Optional[str]
    exchange_type: str
    requested_start_date: str
    requested_end_date: str
    points_cost: int
    hold_ledger_entry_id: Optional[str]
    status: str
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExchangeAgreement(TypedDict):
    id: str
    request_id: str
    guest_member_id: str
    host_member_id: str
    listing_id: str
    availability_window_id: str
    exchange_type: str
    check_in: str
    check_out: str
    points_cost: int
    coverage_limit_points: int
    insurance_status: str
    refund_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger entry carries only id + created_at
class PointsLedgerEntry(TypedDict):
    id: str
    member_id: str
    agreement_id: Optional[str]
    entry_type: str
    amount: int
    status: str
    memo: Optional[str]
    created_at: str


class DamageClaim(TypedDict):
    id: str
    agreement_id: str
    claimant_member_id: str
    respondent_member_id: str
    claimed_amount: int
    assessed_amount: Optional[int]
    provisional_payout: int
    deductible_points: int
    final_payout: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    agreement_id: str
    opened_by_member_id: str
    respondent_member_id: str
    reason: str
    penalty_points: int
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
