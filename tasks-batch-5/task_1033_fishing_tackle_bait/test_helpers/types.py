"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this system carries the full set of common fields
(id, created_at, updated_at, version) per the PRD's resource-identity rules.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SHOP_CLERK = "ShopClerk"
    GUIDE = "Guide"
    TOURNAMENT_DIRECTOR = "TournamentDirector"
    SHOP_MANAGER = "ShopManager"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class CustomerTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ProductCategory(str, Enum):
    ROD = "ROD"
    REEL = "REEL"
    TERMINAL_TACKLE = "TERMINAL_TACKLE"
    APPAREL = "APPAREL"
    DRY_BAIT = "DRY_BAIT"


class LicenseType(str, Enum):
    RESIDENT_ANNUAL = "RESIDENT_ANNUAL"
    NONRESIDENT_ANNUAL = "NONRESIDENT_ANNUAL"
    ONE_DAY = "ONE_DAY"
    SENIOR = "SENIOR"


class LicenseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class BaitSpecies(str, Enum):
    MINNOW = "MINNOW"
    SHINER = "SHINER"
    NIGHTCRAWLER = "NIGHTCRAWLER"
    SHRIMP = "SHRIMP"


class BaitTankStatus(str, Enum):
    EMPTY = "EMPTY"
    LOW = "LOW"
    HEALTHY = "HEALTHY"


class GuideStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUSPENDED = "SUSPENDED"


class WaterType(str, Enum):
    LAKE = "LAKE"
    RIVER = "RIVER"
    SALTWATER = "SALTWATER"
    POND = "POND"


class TripType(str, Enum):
    HALF_DAY = "HALF_DAY"
    FULL_DAY = "FULL_DAY"


class CharterBookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TournamentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class TournamentEntryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WEIGHED = "WEIGHED"
    PLACED = "PLACED"


class ServiceType(str, Enum):
    SPOOLING = "SPOOLING"
    REEL_SERVICE = "REEL_SERVICE"
    ROD_REPAIR = "ROD_REPAIR"
    GUIDE_LINE = "GUIDE_LINE"


class ServiceOrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_PARTS = "AWAITING_PARTS"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ORDERED = "ORDERED"
    ARRIVED = "ARRIVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class SaleStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


# --------------------------------------------------------------------------
# Entity TypedDicts (all entities carry the common fields)
# --------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    name: str
    email: str
    state_code: str
    birth_date: str
    loyalty_ledger: list
    loyalty_points_balance: int
    loyalty_tier: str
    lifetime_spend_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_price_cents: int
    stock_qty: int
    is_active: bool
    is_special_order_eligible: bool
    created_at: str
    updated_at: str
    version: int


class FishingLicense(TypedDict):
    id: str
    customer_id: str
    license_type: str
    state_code: str
    valid_from: str
    valid_to: str
    price_cents: int
    status: str
    is_voided: bool
    issued_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class BaitTank(TypedDict):
    id: str
    name: str
    species: str
    capacity_units: int
    mortality_rate_bps_per_day: int
    batches: list
    sold_count: int
    available_count: int
    low_stock_threshold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Guide(TypedDict):
    id: str
    name: str
    guide_license_no: str
    half_day_rate_cents: int
    full_day_rate_cents: int
    per_extra_angler_cents: int
    max_party_size: int
    fuel_surcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    water_type: str
    daily_permit_cents: int
    created_at: str
    updated_at: str
    version: int


class CharterBooking(TypedDict):
    id: str
    customer_id: str
    guide_id: str
    venue_id: str
    trip_type: str
    party_size: int
    start_at: str
    end_at: str
    add_equipment_rental: bool
    status: str
    season_at_quote: Optional[str]
    provisional_total_cents: Optional[int]
    deposit_cents: Optional[int]
    final_total_cents: Optional[int]
    points_awarded: Optional[int]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tournament(TypedDict):
    id: str
    venue_id: str
    name: str
    entry_fee_cents: int
    bag_limit: int
    registration_open_at: str
    registration_close_at: str
    start_at: str
    end_at: str
    max_entries: int
    prize_points: int
    status: str
    entry_count: int
    winner_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TournamentEntry(TypedDict):
    id: str
    tournament_id: str
    customer_id: str
    status: str
    entry_fee_paid_cents: int
    weigh_ins: list
    bag_weight_grams: int
    big_fish_grams: int
    placement: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    customer_id: str
    item_description: str
    service_type: str
    quoted_cents: int
    line_length_yards: Optional[int]
    status: str
    final_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    quantity: int
    unit_price_cents: int
    deposit_cents: int
    status: str
    refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    customer_id: str
    clerk_user_id: str
    lines: list
    status: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    points_provisional: Optional[int]
    points_final: Optional[int]
    created_at: str
    updated_at: str
    version: int
