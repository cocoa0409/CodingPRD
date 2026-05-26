"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ----------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    OWNER = "Owner"
    SITTER = "Sitter"
    PLATFORM_ADMIN = "PlatformAdmin"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


# --- Status enums -------------------------------------------------------------

class SitterStatus(str, Enum):
    APPLIED = "APPLIED"
    BG_CHECK_PENDING = "BG_CHECK_PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class SitterTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class BackgroundCheckStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class BackgroundCheckProvider(str, Enum):
    CHECKR = "CHECKR"
    ACCURATE = "ACCURATE"
    FIRST_ADVANTAGE = "FIRST_ADVANTAGE"


class PetSpecies(str, Enum):
    DOG = "DOG"
    CAT = "CAT"


class EmergencyContactRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    PARENT = "PARENT"
    FRIEND = "FRIEND"
    VET = "VET"
    NEIGHBOR = "NEIGHBOR"
    OTHER = "OTHER"


class MeetAndGreetStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED_APPROVED = "COMPLETED_APPROVED"
    COMPLETED_DECLINED = "COMPLETED_DECLINED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BookingServiceType(str, Enum):
    WALK_30MIN = "WALK_30MIN"
    WALK_60MIN = "WALK_60MIN"
    BOARDING_OVERNIGHT = "BOARDING_OVERNIGHT"
    DAYCARE = "DAYCARE"


class BookingTimeOfDay(str, Enum):
    STANDARD = "STANDARD"
    PEAK = "PEAK"
    OVERNIGHT = "OVERNIGHT"


class BookingRecurringCadence(str, Enum):
    NONE = "NONE"
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    KEY_RECEIVED = "KEY_RECEIVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EMERGENCY_TERMINATED = "EMERGENCY_TERMINATED"


class KeyHandoffMethod(str, Enum):
    LOCKBOX = "LOCKBOX"
    IN_PERSON = "IN_PERSON"
    SMART_LOCK = "SMART_LOCK"


class KeyHandoffStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    RETURNED = "RETURNED"
    LOST = "LOST"


class InsuranceClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


# --- Entity TypedDicts (common_fields: true → id, created_at, updated_at, version) ---

class Owner(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    phone: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Sitter(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    phone: str
    status: str
    tier: str
    tier_score: int
    total_completed_bookings: int
    total_rating_sum: int
    total_rating_count: int
    claim_count: int
    pending_payout_cents: int
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict, total=False):
    id: str
    sitter_id: str
    provider: str
    status: str
    cleared_at: Optional[str]
    flagged_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Pet(TypedDict, total=False):
    id: str
    owner_id: str
    name: str
    species: str
    weight_kg: float
    medical_notes: str
    created_at: str
    updated_at: str
    version: int


class EmergencyContact(TypedDict, total=False):
    id: str
    owner_id: str
    full_name: str
    phone: str
    relationship: str
    priority: int
    created_at: str
    updated_at: str
    version: int


class MeetAndGreet(TypedDict, total=False):
    id: str
    owner_id: str
    sitter_id: str
    pet_id: str
    scheduled_at: str
    status: str
    decided_at: Optional[str]
    notes: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    owner_id: str
    sitter_id: str
    pet_id: str
    service_type: str
    time_of_day: str
    recurring_cadence: str
    start_at: str
    end_at: str
    status: str
    emergency_surcharge_cents: int
    booking_quote_cents: int
    provisional_sitter_payout_cents: int
    final_sitter_payout_cents: int
    tip_cents: int
    incident_deduction_cents: int
    owner_rating: Optional[int]
    wallet_credit_applied_cents: int
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KeyHandoff(TypedDict, total=False):
    id: str
    booking_id: str
    method: str
    status: str
    lockbox_code: Optional[str]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# GpsTrack carries common_fields: false — only id and created_at.
class GpsTrack(TypedDict, total=False):
    id: str
    booking_id: str
    latitude: float
    longitude: float
    recorded_at: str
    created_at: str


class InsuranceClaim(TypedDict, total=False):
    id: str
    booking_id: str
    sitter_id_snapshot: str
    sitter_tier_snapshot: str
    claim_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    provisional_payout_cents: int
    final_payout_cents: int
    adjuster_notes: str
    denied_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
