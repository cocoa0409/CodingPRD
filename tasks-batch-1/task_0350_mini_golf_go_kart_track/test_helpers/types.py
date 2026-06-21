"""Domain types: entity TypedDicts, status enums, role enum.

All names use the PRD's domain terminology for the Mini-Golf & Go-Kart Track API.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status / enum value sets ─────────────────────────────────────────────────

class VenuePosture(str, Enum):
    OPEN = "OPEN"
    WEATHER_HOLD = "WEATHER_HOLD"
    CLOSED = "CLOSED"


class AttractionKind(str, Enum):
    GO_KART = "GO_KART"
    MINI_GOLF = "MINI_GOLF"
    ARCADE = "ARCADE"


class AttractionStatus(str, Enum):
    ACTIVE = "ACTIVE"


class PricingMode(str, Enum):
    PER_ROUND = "PER_ROUND"
    PER_HEAT = "PER_HEAT"
    WRISTBAND = "WRISTBAND"


class SlotWindow(str, Enum):
    OFF_PEAK = "OFF_PEAK"
    PEAK = "PEAK"


class SlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class WaiverStatus(str, Enum):
    NONE = "NONE"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"


class ComboPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class PartyGroupStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    HOLD = "HOLD"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BookingSlotKind(str, Enum):
    HEAT = "HEAT"
    TEE_SESSION = "TEE_SESSION"


class BookingOrigin(str, Enum):
    RESERVATION = "RESERVATION"
    WALK_IN = "WALK_IN"


class UserRole(str, Enum):
    OPS_MANAGER = "OpsManager"
    CASHIER = "Cashier"
    GUEST = "Guest"


# ─── Entity TypedDicts ────────────────────────────────────────────────────────
# Resources that carry common fields hold id, created_at, updated_at, version.
# Waiver is immutable and carries ONLY id + created_at (no updated_at, no version).

class Venue(TypedDict):
    id: str
    name: str
    timezone: str
    posture: str
    weather_hold_reason: Optional[str]
    current_utc: str
    open_slot_count: int
    created_at: str
    updated_at: str
    version: int


class Attraction(TypedDict):
    id: str
    venue_id: str
    name: str
    kind: str
    min_height_cm: int
    lane_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PricingPlan(TypedDict):
    id: str
    venue_id: str
    name: str
    mode: str
    base_price_cents: int
    peak_surcharge_cents: int
    group_discount_pct: float
    wristband_unit_cap: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Heat(TypedDict):
    id: str
    venue_id: str
    attraction_id: str
    start_utc: str
    end_utc: str
    window: str
    lane_capacity: int
    lanes_committed: int
    lanes_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TeeSession(TypedDict):
    id: str
    venue_id: str
    attraction_id: str
    start_utc: str
    end_utc: str
    window: str
    party_slot_capacity: int
    players_committed: int
    players_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    full_name: str
    height_cm: int
    birthdate: Optional[str]
    waiver_status: str
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    guest_id: str
    signed_at: str
    expires_at: str
    guardian_name: Optional[str]
    created_at: str


class Wallet(TypedDict):
    id: str
    guest_id: str
    arcade_card_balance_cents: int
    total_loaded_cents: int
    created_at: str
    updated_at: str
    version: int


class ComboPass(TypedDict):
    id: str
    guest_id: str
    total_credits: int
    credits_redeemed: int
    credits_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartyGroup(TypedDict):
    id: str
    venue_id: str
    host_guest_id: str
    package_name: str
    included_unit_count: int
    deposit_cents: int
    units_consumed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    venue_id: str
    guest_id: str
    slot_kind: str
    heat_id: Optional[str]
    tee_session_id: Optional[str]
    pricing_plan_id: str
    group_id: Optional[str]
    combo_pass_id: Optional[str]
    origin: str
    party_size: int
    units: int
    gross_price_cents: int
    credits_applied: int
    cash_due_cents: int
    status: str
    waitlist_seq: Optional[int]
    created_at: str
    updated_at: str
    version: int
