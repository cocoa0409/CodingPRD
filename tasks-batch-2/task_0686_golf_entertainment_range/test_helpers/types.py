"""Domain types: entity TypedDicts, status enums, role enum.

All names use the PRD's domain terminology (Golf Entertainment Range API).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────────
class UserRole(str, Enum):
    GUEST = "Guest"
    FRONT_DESK = "FrontDesk"
    RANGE_MANAGER = "RangeManager"


# ─── Status enums ─────────────────────────────────────────────────────────
class BayStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class MemberTier(str, Enum):
    STANDARD = "STANDARD"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class GameCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"


class GiftCardStatus(str, Enum):
    ISSUED = "ISSUED"
    DEPLETED = "DEPLETED"


class ReservationStatus(str, Enum):
    HOLD = "HOLD"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PlayStatus(str, Enum):
    OPEN = "OPEN"
    ENDED = "ENDED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    CHARGED = "CHARGED"
    VOID = "VOID"


class EventPackageStatus(str, Enum):
    QUOTED = "QUOTED"
    NEGOTIATING = "NEGOTIATING"
    CONFIRMED = "CONFIRMED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class FBTabStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class QueueTicketStatus(str, Enum):
    WAITING = "WAITING"
    SEATED = "SEATED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class LessonKind(str, Enum):
    PRIVATE_LESSON = "PRIVATE_LESSON"
    GROUP_CLINIC = "GROUP_CLINIC"
    SIMULATOR = "SIMULATOR"


class LessonStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ChargeKind(str, Enum):
    BAY_RESERVATION = "BAY_RESERVATION"
    SESSION_SETTLEMENT = "SESSION_SETTLEMENT"
    EVENT_SETTLEMENT = "EVENT_SETTLEMENT"
    NO_SHOW_FEE = "NO_SHOW_FEE"


class ChargeStatus(str, Enum):
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class PaySource(str, Enum):
    WALLET = "WALLET"
    CARD_ON_FILE = "CARD_ON_FILE"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Entities carrying id + created_at + updated_at + version (versioned resources).

class Venue(TypedDict):
    id: str
    name: str
    bay_count: int
    open_minute_of_day: int
    close_minute_of_day: int
    base_rate_cents_per_half_hour: int
    peak_demand_factor: float
    open_queue_length: int
    available_bay_count: int
    created_at: str
    updated_at: str
    version: int


class Bay(TypedDict):
    id: str
    venue_id: str
    label: str
    floor_level: int
    has_target_tech: bool
    status: str
    current_session_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    tier: str
    wallet_balance_cents: int
    loyalty_points: int
    pending_loyalty_points: int
    created_at: str
    updated_at: str
    version: int


class GameCard(TypedDict):
    id: str
    member_id: str
    credits_total: int
    credits_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    venue_id: str
    bay_id: str
    member_id: str
    start_utc: str
    end_utc: str
    day_type: str
    time_band: str
    pay_source: str
    quoted_price_cents: int
    status: str
    hold_expires_utc: str
    charge_id: Optional[str]
    no_show_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class GameSession(TypedDict):
    id: str
    bay_id: str
    member_id: str
    reservation_id: Optional[str]
    queue_ticket_id: Optional[str]
    play_status: str
    billing_status: str
    total_score: int
    shot_count: int
    shots: List[dict]
    charge_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EventPackage(TypedDict):
    id: str
    venue_id: str
    organizer_member_id: str
    headcount_estimate: int
    actual_attendee_count: Optional[int]
    per_head_package_cents: int
    bay_block_cents: int
    deposit_cents: int
    estimated_total_cents: int
    final_total_cents: Optional[int]
    deposit_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FBTab(TypedDict):
    id: str
    session_id: Optional[str]
    event_package_id: Optional[str]
    line_items: List[dict]
    subtotal_cents: int
    gratuity_cents: int
    tax_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QueueTicket(TypedDict):
    id: str
    venue_id: str
    member_id: str
    game_card_id: Optional[str]
    party_size: int
    position: int
    status: str
    assigned_bay_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lesson(TypedDict):
    id: str
    venue_id: str
    bay_id: str
    member_id: str
    kind: str
    start_utc: str
    end_utc: str
    seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable resources — carry ONLY id + created_at (no updated_at, no version).

class GiftCard(TypedDict):
    id: str
    face_value_cents: int
    remaining_cents: int
    redeemed_total_cents: int
    status: str
    created_at: str


class Charge(TypedDict):
    id: str
    member_id: str
    kind: str
    amount_cents: int
    pay_source: str
    status: str
    created_at: str
