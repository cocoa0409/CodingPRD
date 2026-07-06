"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    OPS_MANAGER = "OpsManager"
    BOX_OFFICE = "BoxOffice"
    GUEST = "Guest"
    ACTOR = "Actor"


# ─── Status / tier enums ──────────────────────────────────────────────────
class VenueWeatherStatus(str, Enum):
    CLEAR = "CLEAR"
    ADVISORY = "ADVISORY"
    SEVERE = "SEVERE"


class VenueOperationalState(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SHUTDOWN = "SHUTDOWN"


class AttractionStatus(str, Enum):
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class TimeSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CLOSED = "CLOSED"


class WaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ReservationEntryStatus(str, Enum):
    HELD = "HELD"
    RESERVED = "RESERVED"
    ADMITTED = "ADMITTED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ReservationPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class PassProductKind(str, Enum):
    SEASON = "SEASON"
    GROUP = "GROUP"


class TicketTier(str, Enum):
    GA = "GA"
    FAST_PASS = "FAST_PASS"
    VIP = "VIP"


class ScareZoneStaffingStatus(str, Enum):
    UNDERSTAFFED = "UNDERSTAFFED"
    STAFFED = "STAFFED"


class ActorShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class ClosureReason(str, Enum):
    WEATHER = "WEATHER"
    SAFETY = "SAFETY"
    UNDERSTAFFED = "UNDERSTAFFED"


class ClosureStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Entities carrying the full common-field set: id, created_at, updated_at, version.

class Venue(TypedDict):
    id: str
    name: str
    timezone: str
    weather_status: str
    operational_state: str
    open_attraction_count: int
    created_at: str
    updated_at: str
    version: int


class Attraction(TypedDict):
    id: str
    venue_id: str
    name: str
    min_age: int
    scare_level: int
    throughput_per_slot: int
    status: str
    requires_waiver: bool
    created_at: str
    updated_at: str
    version: int


class TimeSlot(TypedDict):
    id: str
    attraction_id: str
    window_start: str
    window_end: str
    capacity: int
    reserved_count: int
    admitted_count: int
    demand_ratio: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    full_name: str
    age: int
    email: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    guest_id: str
    max_scare_level: int
    signed_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    venue_id: str
    guest_id: str
    pass_id: Optional[str]
    party_size: int
    entry_status: str
    payment_status: str
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    reservation_id: str
    time_slot_id: str
    guest_age: int
    max_scare_level: int
    tier: str
    price_cents: int
    queue_priority: int
    created_at: str
    updated_at: str
    version: int


class Pass(TypedDict):
    id: str
    pass_product_id: str
    guest_id: str
    redemptions_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScareZone(TypedDict):
    id: str
    attraction_id: str
    name: str
    min_actors: int
    checked_in_count: int
    staffing_status: str
    created_at: str
    updated_at: str
    version: int


class ActorShift(TypedDict):
    id: str
    scare_zone_id: str
    actor_user_id: str
    shift_start: str
    shift_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Closure(TypedDict):
    id: str
    attraction_id: str
    reason: str
    opened_reservation_refunds: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable entities — carry ONLY id + created_at (no updated_at, no version).

class PricingRule(TypedDict):
    id: str
    attraction_id: str
    tier: str
    base_price_cents: int
    low_demand_max_ratio: float
    high_demand_min_ratio: float
    mid_surge_pct: int
    high_surge_pct: int
    created_at: str


class PassProduct(TypedDict):
    id: str
    venue_id: str
    kind: str
    price_cents: int
    discount_pct: int
    min_party: int
    max_redemptions: int
    created_at: str
