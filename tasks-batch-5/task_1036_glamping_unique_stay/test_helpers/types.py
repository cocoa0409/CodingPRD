"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    HOST = "Host"
    GUEST = "Guest"
    PERMIT_REVIEWER = "PermitReviewer"
    PLATFORM_ADMIN = "PlatformAdmin"


class PayoutMethod(str, Enum):
    BANK = "BANK"
    PAYPAL = "PAYPAL"


class SiteType(str, Enum):
    YURT = "YURT"
    CABIN = "CABIN"
    TREEHOUSE = "TREEHOUSE"
    DOME = "DOME"
    AIRSTREAM = "AIRSTREAM"


class CancellationPolicy(str, Enum):
    FLEXIBLE = "FLEXIBLE"
    MODERATE = "MODERATE"
    STRICT = "STRICT"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PERMIT = "PENDING_PERMIT"
    LISTED = "LISTED"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


class PermitType(str, Enum):
    CAMPING = "CAMPING"
    STRUCTURE = "STRUCTURE"
    SPECIAL_USE = "SPECIAL_USE"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AddOnCategory(str, Enum):
    AMENITY = "AMENITY"
    EXPERIENCE = "EXPERIENCE"


class PricingUnit(str, Enum):
    PER_STAY = "PER_STAY"
    PER_NIGHT = "PER_NIGHT"
    PER_GUEST = "PER_GUEST"


class AddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class PayoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    PARTIAL = "PARTIAL"
    VOIDED = "VOIDED"


class SenderRole(str, Enum):
    HOST = "HOST"
    GUEST = "GUEST"


# --- Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version) ---

class Host(TypedDict):
    id: str
    display_name: str
    email: str
    payout_method: str
    pending_payout_cents: int
    paid_out_cents: int
    completed_stays_count: int
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    display_name: str
    email: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    host_id: str
    title: str
    site_type: str
    max_guests: int
    min_nights: int
    base_nightly_rate_cents: int
    cleaning_fee_cents: int
    cancellation_policy: str
    status: str
    reserved_nights_count: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    listing_id: str
    permit_type: str
    authority_name: str
    status: str
    review_notes: Optional[str]
    valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeasonalRate(TypedDict):
    id: str
    listing_id: str
    start_date: str
    end_date: str
    nightly_rate_cents: int
    min_nights_override: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    listing_id: str
    name: str
    category: str
    pricing_unit: str
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExperienceSlot(TypedDict):
    id: str
    add_on_id: str
    slot_date: str
    max_participants: int
    reserved_participants: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    listing_id: str
    guest_id: str
    check_in: str
    check_out: str
    guest_count: int
    nights: int
    status: str
    payment_status: str
    add_ons: List[dict]
    cleaning_fee_snapshot_cents: int
    quoted_total_cents: int
    final_total_cents: Optional[int]
    refund_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    booking_id: str
    estimated_amount_cents: int
    final_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entities (common_fields: false -> only id + created_at) ---

class Review(TypedDict):
    id: str
    booking_id: str
    rating: int
    comment: Optional[str]
    created_at: str


class Message(TypedDict):
    id: str
    booking_id: str
    sender_role: str
    sender_id: str
    body: str
    created_at: str
