"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API carries the common audit fields (id, created_at,
updated_at, version), so every TypedDict below includes them.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    MANAGER = "Manager"
    STAFF = "Staff"
    MEMBER = "Member"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------
class Zone(str, Enum):
    MAIN = "MAIN"
    QUIET = "QUIET"
    PATIO = "PATIO"


class TableStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class MembershipTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class RedemptionStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"
    NONE = "NONE"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    SEATED = "SEATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class FnbOrderStatus(str, Enum):
    OPEN = "OPEN"
    VOID = "VOID"


class GameCopyCondition(str, Enum):
    MINT = "MINT"
    GOOD = "GOOD"
    WORN = "WORN"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class GameCopyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHECKED_OUT = "CHECKED_OUT"
    RETIRED = "RETIRED"


class CheckoutStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    LOST = "LOST"


class TournamentFormat(str, Enum):
    SINGLE_ELIM = "SINGLE_ELIM"
    LEAGUE = "LEAGUE"
    CASUAL = "CASUAL"


class TournamentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    WITHDRAWN = "WITHDRAWN"
    REFUNDED = "REFUNDED"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class PrivateBookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class RetailFulfillmentType(str, Enum):
    IN_STOCK = "IN_STOCK"
    PREORDER = "PREORDER"


class RetailOrderStatus(str, Enum):
    AWAITING_STOCK = "AWAITING_STOCK"
    READY = "READY"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity shapes (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Table(TypedDict):
    id: str
    label: str
    zone: str
    seats: int
    half_hour_rate_cents: int
    day_pass_cents: int
    cover_fee_cents: int
    min_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    email: str
    full_name: str
    tier: str
    points_balance: int
    lifetime_points: int
    no_show_strikes: int
    status: str
    last_redemption_id: Optional[str]
    last_redemption_points: int
    last_redemption_status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    table_id: str
    membership_id: Optional[str]
    party_size: int
    start_at: str
    end_at: str
    deposit_cents: int
    deposit_forfeited: bool
    status: str
    seated_at: Optional[str]
    closed_at: Optional[str]
    tier_at_seating: Optional[str]
    time_charge_cents: int
    cover_charge_cents: int
    member_discount_cents: int
    fnb_subtotal_cents: int
    minimum_shortfall_cents: int
    bill_total_cents: int
    provisional_bill_total_cents: int
    points_earned: int
    created_at: str
    updated_at: str
    version: int


class FnbOrder(TypedDict):
    id: str
    reservation_id: str
    description: str
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GameCopy(TypedDict):
    id: str
    title: str
    barcode: str
    replacement_value_cents: int
    condition: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Checkout(TypedDict):
    id: str
    game_copy_id: str
    reservation_id: str
    checkout_condition: str
    return_condition: Optional[str]
    condition_fee_cents: int
    status: str
    checked_out_at: str
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tournament(TypedDict):
    id: str
    name: str
    game_title: str
    format: str
    capacity: int
    entry_fee_cents: int
    start_at: str
    status: str
    registered_count: int
    checked_in_count: int
    house_cut_cents: int
    provisional_prize_pool_cents: int
    prize_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    tournament_id: str
    membership_id: str
    status: str
    fee_paid_cents: int
    refunded_cents: int
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


class PrivateBooking(TypedDict):
    id: str
    room_id: str
    start_at: str
    end_at: str
    headcount: int
    status: str
    quoted_total_cents: int
    deposit_cents: int
    created_at: str
    updated_at: str
    version: int


class RetailOrder(TypedDict):
    id: str
    membership_id: Optional[str]
    product_title: str
    fulfillment_type: str
    quantity: int
    unit_price_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
