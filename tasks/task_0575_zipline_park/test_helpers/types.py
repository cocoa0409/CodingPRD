"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    OPERATOR = "Operator"
    CUSTOMER = "Customer"
    GUIDE = "Guide"


class TimeSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    COMPLETED = "COMPLETED"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    BRIEFED = "BRIEFED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RAINCHECKED = "RAINCHECKED"
    NO_SHOW = "NO_SHOW"
    REDEEMED = "REDEEMED"


class WaiverStatus(str, Enum):
    NONE = "NONE"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"


class SeasonPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class SeasonPassTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class GroupStatus(str, Enum):
    OPEN = "OPEN"
    CANCELLED = "CANCELLED"


class GuideAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CANCELLED = "CANCELLED"


class GearType(str, Enum):
    HARNESS = "HARNESS"
    HELMET = "HELMET"


class GearSize(str, Enum):
    S = "S"
    M = "M"
    L = "L"


class GearItemStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHECKED_OUT = "CHECKED_OUT"


class GearCheckoutStatus(str, Enum):
    OUT = "OUT"
    RETURNED = "RETURNED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Course(TypedDict):
    id: str
    name: str
    difficulty_level: int
    min_weight_kg: float
    max_weight_kg: float
    min_age_years: int
    base_price_cents: int
    duration_minutes: int
    default_capacity: int
    max_participants_per_guide: int
    weekend_surcharge_pct: float
    created_at: str
    updated_at: str
    version: int


class TimeSlot(TypedDict):
    id: str
    course_id: str
    start_at: str
    end_at: str
    capacity: int
    booked_count: int
    remaining_capacity: int
    status: str
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Guide(TypedDict):
    id: str
    name: str
    certification_level: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    full_name: str
    weight_kg: float
    birthdate: str
    age_years: int
    waiver_status: str
    waiver_signed_at: Optional[str]
    waiver_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeasonPass(TypedDict):
    id: str
    participant_id: str
    tier: str
    valid_from: str
    valid_until: str
    total_uses: int
    uses_committed: int
    uses_settled: int
    uses_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Group(TypedDict):
    id: str
    name: str
    time_slot_id: str
    expected_size: int
    organizer_name: str
    organizer_participant_id: Optional[str]
    member_count: int
    insurance_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    time_slot_id: str
    participant_id: str
    group_id: Optional[str]
    season_pass_id: Optional[str]
    use_season_pass: bool
    status: str
    price_cents: int
    raincheck_credit_cents: int
    redeemed_from_booking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GuideAssignment(TypedDict):
    id: str
    guide_id: str
    time_slot_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GearItem(TypedDict):
    id: str
    gear_type: str
    size: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GearCheckout(TypedDict):
    id: str
    gear_item_id: str
    booking_id: str
    window_start: str
    window_end: str
    checked_out_at: str
    returned_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class IncidentReport(TypedDict):
    id: str
    booking_id: str
    severity: str
    description: str
    reported_by_guide_id: str
    occurred_at: str
    created_at: str
