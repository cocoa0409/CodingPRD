"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    RENTER = "Renter"
    OWNER = "Owner"
    PLATFORM = "Platform"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class VerificationRecordStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    ACTIVE = "ACTIVE"
    EXTENSION_REQUESTED = "EXTENSION_REQUESTED"
    RETURNED = "RETURNED"
    LATE = "LATE"
    COMPLETED = "COMPLETED"


class HandoffStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class HandoffType(str, Enum):
    PICKUP = "PICKUP"
    RETURN = "RETURN"


class DepositStatus(str, Enum):
    HELD = "HELD"
    PARTIALLY_CAPTURED = "PARTIALLY_CAPTURED"
    CAPTURED = "CAPTURED"
    RELEASED = "RELEASED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"


class ClaimType(str, Enum):
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    HELD = "HELD"
    RELEASED = "RELEASED"


class DocumentType(str, Enum):
    PASSPORT = "PASSPORT"
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    NATIONAL_ID = "NATIONAL_ID"


class RatingDirection(str, Enum):
    RENTER_TO_OWNER = "RENTER_TO_OWNER"
    OWNER_TO_RENTER = "OWNER_TO_RENTER"


# --- Entity TypedDicts -------------------------------------------------------

# common_fields: true — id + created_at + updated_at + version
class User(TypedDict):
    id: str
    email: str
    full_name: str
    phone: str
    verification_status: str
    trust_score: int
    avg_rating: Optional[float]
    rating_count: int
    late_return_count: int
    upheld_claim_count: int
    total_earnings_cents: int
    created_at: str
    updated_at: str
    version: int


class VerificationRecord(TypedDict):
    id: str
    user_id: str
    document_type: str
    document_ref: str
    status: str
    valid_from: Optional[str]
    valid_until: Optional[str]
    reject_reason: Optional[str]
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    owner_id: str
    title: str
    category: str
    declared_value_cents: int
    base_daily_rate_cents: int
    deposit_cents: int
    quantity: int
    demand_multiplier_bps: int
    status: str
    active_booking_count: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    listing_id: str
    renter_id: str
    start_date: str
    end_date: str
    expected_listing_version: int
    status: str
    billable_days: int
    rental_subtotal_cents: int
    renter_service_fee_cents: int
    provisional_total_cents: int
    final_total_cents: Optional[int]
    late_days: int
    late_fee_cents: int
    extension_requested_end_date: Optional[str]
    actual_return_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HandoffAppointment(TypedDict):
    id: str
    booking_id: str
    owner_id: str
    type: str
    slot_start: str
    slot_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict):
    id: str
    booking_id: str
    original_amount_cents: int
    held_cents: int
    captured_cents: int
    released_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    booking_id: str
    claim_type: str
    claimed_amount_cents: int
    description: str
    status: str
    provisional_capture_cents: int
    approved_amount_cents: Optional[int]
    deposit_capture_cents: int
    coverage_paid_cents: int
    reviewed_by: Optional[str]
    resolved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    booking_id: str
    owner_id: str
    gross_earnings_cents: int
    owner_commission_cents: int
    damage_reimbursement_cents: int
    net_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only evidence, ONLY id + created_at
class ConditionReport(TypedDict):
    id: str
    booking_id: str
    phase: str
    photo_urls: List[str]
    recorded_by: str
    notes: Optional[str]
    created_at: str


class Rating(TypedDict):
    id: str
    booking_id: str
    rater_id: str
    ratee_id: str
    direction: str
    score: int
    comment: Optional[str]
    created_at: str
