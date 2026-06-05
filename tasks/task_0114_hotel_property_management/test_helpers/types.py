"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    REVENUE_MANAGER = "RevenueManager"
    FRONT_DESK_AGENT = "FrontDeskAgent"
    NIGHT_AUDITOR = "NightAuditor"
    GUEST = "Guest"


# --- Status / enum value sets ---
class HotelPosture(str, Enum):
    OPEN = "OPEN"
    AUDIT_LOCK = "AUDIT_LOCK"


class HousekeepingStatus(str, Enum):
    DIRTY = "DIRTY"
    CLEAN = "CLEAN"
    INSPECTED = "INSPECTED"
    OCCUPIED = "OCCUPIED"
    OUT_OF_ORDER = "OUT_OF_ORDER"


class RatePlanKind(str, Enum):
    BAR = "BAR"
    CORPORATE = "CORPORATE"
    PACKAGE = "PACKAGE"


class AdjustmentMode(str, Enum):
    PCT = "PCT"
    FLAT = "FLAT"


class NoShowPolicy(str, Enum):
    FIRST_NIGHT = "FIRST_NIGHT"
    FULL_STAY = "FULL_STAY"
    NONE = "NONE"


class RatePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class CorporateAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LoyaltyTier(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class GroupBlockStatus(str, Enum):
    OPEN = "OPEN"
    WASHED = "WASHED"
    CLOSED = "CLOSED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class FolioStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DISPUTED = "DISPUTED"


class FolioBillTo(str, Enum):
    GUEST = "GUEST"
    CORPORATE = "CORPORATE"


class IncidentalKind(str, Enum):
    CHARGE = "CHARGE"
    PAYMENT = "PAYMENT"
    ADJUSTMENT = "ADJUSTMENT"


class IncidentalPostedByKind(str, Enum):
    AGENT = "AGENT"
    NIGHT_AUDIT = "NIGHT_AUDIT"


class IncidentalStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class NightAuditStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


# --- Entity TypedDicts (common_fields: true carry id + created_at + updated_at + version) ---
class Hotel(TypedDict):
    id: str
    name: str
    timezone: str
    current_business_date: str
    overbooking_allowance_pct: float
    audit_epoch: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class RoomType(TypedDict):
    id: str
    hotel_id: str
    code: str
    tier_rank: int
    physical_inventory: int
    base_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    hotel_id: str
    room_type_id: str
    room_number: str
    housekeeping_status: str
    assigned_reservation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RatePlan(TypedDict):
    id: str
    hotel_id: str
    code: str
    kind: str
    corporate_account_id: Optional[str]
    adjustment_mode: str
    adjustment_value: int
    package_fee_cents: int
    no_show_policy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CorporateAccount(TypedDict):
    id: str
    hotel_id: str
    name: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    hotel_id: str
    full_name: str
    email: str
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class GroupBlock(TypedDict):
    id: str
    hotel_id: str
    room_type_id: str
    rate_plan_id: str
    block_name: str
    arrival_date: str
    departure_date: str
    cutoff_date: str
    blocked_rooms: int
    picked_up_rooms: int
    washed_rooms: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    hotel_id: str
    guest_id: str
    room_type_id: str
    rate_plan_id: str
    corporate_account_id: Optional[str]
    group_block_id: Optional[str]
    assigned_room_id: Optional[str]
    effective_room_type_id: str
    arrival_date: str
    departure_date: str
    nights: int
    is_upgraded: bool
    upgrade_is_comp: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Folio(TypedDict):
    id: str
    hotel_id: str
    reservation_id: str
    room_charges_cents: int
    projected_charges_cents: int
    incidentals_cents: int
    payments_cents: int
    balance_cents: int
    bill_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Incidental(TypedDict):
    id: str
    hotel_id: str
    folio_id: str
    kind: str
    description: str
    amount_cents: int
    posted_by_kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NightAuditRun(TypedDict):
    id: str
    hotel_id: str
    business_date: str
    epoch: int
    no_show_count: int
    room_postings_count: int
    washed_block_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Availability read-model: pure computed projection; carries ONLY id + created_at ---
class AvailabilityCell(TypedDict):
    id: str
    hotel_id: str
    room_type_id: str
    stay_date: str
    sold_count: int
    sellable_count: int
    created_at: str
