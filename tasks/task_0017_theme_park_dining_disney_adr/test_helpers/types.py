"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model. Entities carrying `id`, `created_at`,
`updated_at`, and `version` are full common-fields entities (PRD §2.4).
NoShowFeeAssessment and CreditLedgerEntry are append-only audit records
carrying only `id` + `created_at`, per PRD §2.4 second paragraph.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status Enums ─────────────────────────────────────────────────────────

class GuestStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ParkSessionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class DiningPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class DiningPlanTier(str, Enum):
    STANDARD = "STANDARD"
    PLUS = "PLUS"
    DELUXE = "DELUXE"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    SEATED = "SEATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class AllergyMealStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PREPARED = "PREPARED"
    SERVED = "SERVED"
    DECLINED = "DECLINED"


class LightningLaneAddOnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ALLOCATED = "ALLOCATED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class LightningLaneTier(str, Enum):
    SINGLE_PASS = "SINGLE_PASS"
    MULTI_PASS = "MULTI_PASS"


class ParkCode(str, Enum):
    MAGIC_KINGDOM = "MAGIC_KINGDOM"
    EPCOT = "EPCOT"
    ANIMAL_KINGDOM = "ANIMAL_KINGDOM"
    HOLLYWOOD_STUDIOS = "HOLLYWOOD_STUDIOS"


class AllergenCode(str, Enum):
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    GLUTEN = "GLUTEN"
    DAIRY = "DAIRY"
    EGG = "EGG"
    SHELLFISH = "SHELLFISH"
    SOY = "SOY"


class CreditLedgerEntryType(str, Enum):
    HOLD = "HOLD"
    RELEASE = "RELEASE"
    DEBIT = "DEBIT"
    REFUND = "REFUND"


class UserRole(str, Enum):
    GUEST = "Guest"
    RESTAURANT = "Restaurant"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts (common_fields=true) ───────────────────────────────

class Guest(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    home_timezone: str
    no_show_strike_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Restaurant(TypedDict, total=False):
    id: str
    name: str
    park_code: str
    capacity_per_slot: int
    slot_minutes: int
    is_character_dining: bool
    dining_plan_credit_cost: int
    no_show_base_fee_cents: int
    opening_local_time: str
    closing_local_time: str
    created_at: str
    updated_at: str
    version: int


class ParkSession(TypedDict, total=False):
    id: str
    guest_id: str
    park_code: str
    visit_date: str
    status: str
    activated_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiningPlan(TypedDict, total=False):
    id: str
    guest_id: str
    tier: str
    table_service_credits_initial: int
    table_service_credits_remaining: int
    table_service_credits_held: int
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    guest_id: str
    restaurant_id: str
    park_session_id: str
    dining_plan_id: str
    slot_start_utc: str
    slot_end_utc: str
    party_size: int
    credits_debited: int
    credits_held: int
    status: str
    confirmed_at: Optional[str]
    checked_in_at: Optional[str]
    no_show_assessed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllergyMeal(TypedDict, total=False):
    id: str
    reservation_id: str
    allergen_codes: List[str]
    notes: str
    status: str
    declined_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LightningLaneAddOn(TypedDict, total=False):
    id: str
    reservation_id: str
    tier: str
    fee_cents: int
    status: str
    allocated_at: Optional[str]
    redemption_window_end_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Entity TypedDicts (common_fields=false: id + created_at only) ────────

class NoShowFeeAssessment(TypedDict, total=False):
    id: str
    reservation_id: str
    guest_id: str
    base_amount_cents: int
    character_surcharge_cents: int
    repeat_offender_multiplier: float
    total_amount_cents: int
    assessed_at: str
    created_at: str


class CreditLedgerEntry(TypedDict, total=False):
    id: str
    dining_plan_id: str
    reservation_id: str
    entry_type: str
    credits_delta: int
    posted_at: str
    created_at: str
