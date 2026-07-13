"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror the PRD field names exactly (integer cents, integer points).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    MEMBER = "Member"
    CASHIER = "Cashier"
    ATTENDANT = "Attendant"
    COORDINATOR = "Coordinator"
    MANAGER = "Manager"


# --- Status / tier enums ---
class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MembershipTier(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class GameCardStatus(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class AttractionStatus(str, Enum):
    OPEN = "OPEN"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class PrizeItemStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    DISCONTINUED = "DISCONTINUED"


class RedemptionStatus(str, Enum):
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class PartyBookingStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WristbandStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    VOID = "VOID"


class DailyReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"
    DISCREPANCY = "DISCREPANCY"


class LedgerEntryType(str, Enum):
    RELOAD = "RELOAD"
    BONUS_GRANT = "BONUS_GRANT"
    GAMEPLAY_DEBIT = "GAMEPLAY_DEBIT"
    POINTS_EARN = "POINTS_EARN"
    POINTS_HOLD = "POINTS_HOLD"
    POINTS_SETTLE = "POINTS_SETTLE"
    POINTS_REFUND = "POINTS_REFUND"
    BONUS_CLAWBACK = "BONUS_CLAWBACK"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---
class Member(TypedDict):
    id: str
    email: str
    full_name: str
    promo_opt_in: bool
    lifetime_spend_cents: int
    membership_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GameCard(TypedDict):
    id: str
    owner_member_id: Optional[str]
    status: str
    chip_balance_cents: int
    bonus_chip_balance_cents: int
    ticket_points_balance: int
    created_at: str
    updated_at: str
    version: int


class Attraction(TypedDict):
    id: str
    name: str
    chip_cost_cents: int
    points_award: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrizeItem(TypedDict):
    id: str
    name: str
    points_price: int
    stock_qty: int
    reserved_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Redemption(TypedDict):
    id: str
    card_id: str
    prize_item_id: str
    quantity: int
    points_hold: int
    points_settled: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PartyPackage(TypedDict):
    id: str
    name: str
    base_price_cents: int
    included_guests: int
    included_hours: int
    included_chip_cents: int
    tier: str
    combo_name: str
    combo_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    name: str
    capacity: int
    hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartyBooking(TypedDict):
    id: str
    room_id: str
    package_id: str
    host_member_id: str
    start_at: str
    end_at: str
    guest_count: int
    status: str
    checked_in_at: Optional[str]
    completed_at: Optional[str]
    provisional_total_cents: Optional[int]
    final_total_cents: Optional[int]
    actual_guest_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Wristband(TypedDict):
    id: str
    booking_id: Optional[str]
    card_id: Optional[str]
    band_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyReconciliation(TypedDict):
    id: str
    business_day: str
    expected_chip_liability_cents: int
    expected_prize_units: int
    counted_chip_liability_cents: Optional[int]
    counted_prize_units: Optional[int]
    variance_chip_cents: Optional[int]
    variance_prize_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only records (common_fields: false — id + created_at only) ---
class CardLedgerEntry(TypedDict):
    id: str
    card_id: str
    entry_type: str
    chip_delta_cents: int
    bonus_delta_cents: int
    points_delta: int
    business_day: str
    note: str
    occurred_at: str
    created_at: str


class GamePlay(TypedDict):
    id: str
    card_id: str
    attraction_id: str
    chip_cost_cents: int
    chip_from_bonus_cents: int
    chip_from_stored_cents: int
    points_awarded: int
    business_day: str
    created_at: str
