"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the Outdoor Gear Rental PRD. Mutable resources carry
id + created_at + updated_at + version; append-only resources carry only
id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Enums ---------------------------------------------------------------

class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    RENTAL_AGENT = "RentalAgent"
    RENTER = "Renter"


class GearCategory(str, Enum):
    KAYAK = "KAYAK"
    SKI = "SKI"
    SUP = "SUP"
    SNOWBOARD = "SNOWBOARD"


class SkillLevel(str, Enum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    EXPERT = "EXPERT"


class CustomerStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class AddOnKind(str, Enum):
    LESSON = "LESSON"
    PACKAGE = "PACKAGE"


class GearCondition(str, Enum):
    GOOD = "GOOD"
    WORN = "WORN"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class GearAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    CHECKED_OUT = "CHECKED_OUT"
    INSPECTING = "INSPECTING"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class ReservationLifecycle(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    PICKED_UP = "PICKED_UP"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class RateBasis(str, Enum):
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    SEASONAL = "SEASONAL"


class ConditionPhase(str, Enum):
    CHECKOUT = "CHECKOUT"
    CHECKIN = "CHECKIN"


class DamageOutcome(str, Enum):
    NONE = "NONE"
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"


class DamageStatus(str, Enum):
    ASSESSED = "ASSESSED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class LedgerEntryType(str, Enum):
    DEPOSIT_HOLD = "DEPOSIT_HOLD"
    DEPOSIT_REFUND = "DEPOSIT_REFUND"
    RENTAL_CHARGE = "RENTAL_CHARGE"
    LATE_FEE = "LATE_FEE"
    DAMAGE_FEE = "DAMAGE_FEE"
    LOSS_FEE = "LOSS_FEE"


# --- Mutable entities (id + created_at + updated_at + version) ------------

class GearType(TypedDict):
    id: str
    category: str
    name: str
    size_label: str
    requires_lesson_for_beginner: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    gear_type_id: str
    hourly_cents: int
    daily_cents: int
    seasonal_flat_cents: int
    deposit_cents: int
    damage_waiver_cents_per_day: int
    late_fee_cents_per_hour: int
    loss_fee_cents: int
    grace_minutes: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    skill_level: str
    standing: str
    strike_points: int
    open_loss_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    kind: str
    category: str
    name: str
    price_cents: int
    capacity_per_slot: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class GearUnit(TypedDict):
    id: str
    gear_type_id: str
    rate_card_id: str
    asset_tag: str
    condition: str
    availability: str
    active_reservation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    customer_id: str
    gear_unit_id: str
    rate_card_id: str
    pickup_at: str
    due_at: str
    picked_up_at: Optional[str]
    returned_at: Optional[str]
    lifecycle_status: str
    payment_status: str
    quoted_rate_basis: str
    quoted_total_cents: int
    deposit_cents: int
    final_total_cents: Optional[int]
    late_fee_cents: int
    damage_waiver_opted: bool
    created_at: str
    updated_at: str
    version: int


class DamageAssessment(TypedDict):
    id: str
    reservation_id: str
    checkin_report_id: str
    outcome: str
    charge_cents: int
    waiver_applied: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entities (id + created_at only) -------------------------

class SeasonWindow(TypedDict):
    id: str
    category: str
    label: str
    starts_on: str
    ends_on: str
    demand_multiplier_bp: int
    created_at: str


class ReservationAddOn(TypedDict):
    id: str
    reservation_id: str
    addon_id: str
    slot_start_at: Optional[str]
    slot_end_at: Optional[str]
    price_cents: int
    created_at: str


class ConditionReport(TypedDict):
    id: str
    reservation_id: str
    gear_unit_id: str
    phase: str
    condition_rating: str
    notes: str
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    reservation_id: str
    customer_id: str
    entry_type: str
    amount_cents: int
    settled: bool
    created_at: str
