"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resources, their state machines, and the role catalogue.
Monetary values are integer cents throughout (PRD §2.8).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) -------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    FRONT_DESK = "FrontDesk"
    LEAGUE_ADMIN = "LeagueAdmin"
    CENTER_MANAGER = "CenterManager"


# --- Status enums (PRD §3 state machines) ---------------------------------
class LaneStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class BayStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ReservationStatus(str, Enum):
    DRAFT = "DRAFT"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    NO_SHOW = "NO_SHOW"
    WAITLISTED = "WAITLISTED"


class RentalItemKind(str, Enum):
    SHOES = "SHOES"
    BALL = "BALL"
    BUMPER = "BUMPER"


class RentalLineStatus(str, Enum):
    OPEN = "OPEN"
    RETURNED = "RETURNED"


class ResourceKind(str, Enum):
    LANE = "LANE"
    BAY = "BAY"


class Origin(str, Enum):
    RESERVATION = "RESERVATION"
    WALK_IN = "WALK_IN"


class PricingMode(str, Enum):
    PER_GAME = "PER_GAME"
    PER_HOUR = "PER_HOUR"


class LeagueStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class LeagueNightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PLAYED = "PLAYED"
    FORFEITED = "FORFEITED"
    RAINED_OUT = "RAINED_OUT"


# --- Entity TypedDicts ----------------------------------------------------
# Resources carrying the full common-field set (id/created_at/updated_at/version)
# per PRD §2.4.

class RateCard(TypedDict):
    id: str
    name: str
    per_game_cents: int
    per_hour_cents: int
    block_minutes: int
    peak_multiplier_bps: int
    peak_start_hour: int
    peak_end_hour: int
    deposit_pct_bps: int
    created_at: str
    updated_at: str
    version: int


class Lane(TypedDict):
    id: str
    number: int
    max_bowlers: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bay(TypedDict):
    id: str
    name: str
    capacity: int
    cleanup_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    deposit_balance_cents: int
    wallet_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartyPackage(TypedDict):
    id: str
    name: str
    base_cents: int
    included_guests: int
    extra_guest_cents: int
    max_guests: int
    included_lane_hours: int
    created_at: str
    updated_at: str
    version: int


class FoodItem(TypedDict):
    id: str
    name: str
    unit_cents: int
    taxable: bool
    created_at: str
    updated_at: str
    version: int


class RentalItem(TypedDict):
    id: str
    kind: str
    label: str
    unit_price_cents: int
    total_count: int
    out_on_rent_count: int
    available_count: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    customer_id: str
    rate_card_id: str
    resource_kind: str
    lane_id: Optional[str]
    bay_id: Optional[str]
    party_package_id: Optional[str]
    origin: str
    pricing_mode: str
    start_at: str
    end_at: str
    bowler_count: int
    game_count: int
    guest_count: int
    lane_subtotal_cents: int
    package_subtotal_cents: int
    food_subtotal_cents: int
    rental_subtotal_cents: int
    quoted_total_cents: int
    held_deposit_cents: int
    refund_cents: int
    status: str
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# FoodOrderLine is deliberately leaner (PRD §2.4): id + created_at only,
# NO updated_at, NO version.
class FoodOrderLine(TypedDict):
    id: str
    reservation_id: str
    food_item_id: str
    quantity: int
    unit_cents_snapshot: int
    taxable_snapshot: bool
    line_total_cents: int
    created_at: str


class RentalLine(TypedDict):
    id: str
    reservation_id: str
    rental_item_id: str
    quantity: int
    unit_price_snapshot: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class League(TypedDict):
    id: str
    name: str
    rate_card_id: str
    season_night_count: int
    lanes_per_night: int
    weekly_fee_cents: int
    season_fee_quote_cents: int
    season_fee_accrued_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeagueNight(TypedDict):
    id: str
    league_id: str
    night_index: int
    start_at: str
    end_at: str
    reserved_lane_ids: List[str]
    status: str
    night_fee_cents: int
    created_at: str
    updated_at: str
    version: int
