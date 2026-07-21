"""Domain types: entity TypedDicts, status enums, role enum.

All types describe the Pool & Billiards Hall API contract. Every persisted
resource carries id/created_at/updated_at/version (Section 2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---- Role enum ----
class UserRole(str, Enum):
    MEMBER = "Member"
    FRONT_DESK = "FrontDesk"
    MANAGER = "Manager"
    PRO_SHOP_STAFF = "ProShopStaff"


# ---- Status enums ----
class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class TableStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class FnbOrderStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    VOIDED = "VOIDED"


class TournamentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    SEEDED = "SEEDED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TournamentEntryStatus(str, Enum):
    ENTERED = "ENTERED"
    CHECKED_IN = "CHECKED_IN"
    WITHDRAWN = "WITHDRAWN"
    ELIMINATED = "ELIMINATED"


class RepairOrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class EventBookingStatus(str, Enum):
    INQUIRY = "INQUIRY"
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


# ---- Entity TypedDicts (all carry common fields id/created_at/updated_at/version) ----
class MembershipPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    table_discount_pct: float
    included_hours_per_month: int
    reservation_horizon_days: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    plan_id: str
    pending_plan_id: Optional[str]
    membership_status: str
    membership_expires_at: str
    handicap_rating: int
    wallet_credit_cents: int
    no_show_strikes: int
    created_at: str
    updated_at: str
    version: int


class PoolTable(TypedDict):
    id: str
    table_number: int
    table_type: str
    seat_capacity: int
    hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    member_id: str
    table_id: str
    event_id: Optional[str]
    start_at: str
    end_at: str
    party_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TableSession(TypedDict):
    id: str
    reservation_id: Optional[str]
    table_id: str
    member_id: Optional[str]
    started_at: str
    ended_at: Optional[str]
    provisional_charge_cents: int
    final_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FnbOrder(TypedDict):
    id: str
    session_id: str
    member_id: Optional[str]
    line_items: List[dict]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Tournament(TypedDict):
    id: str
    name: str
    format: str
    handicap_mode: str
    entry_fee_cents: int
    max_entries: int
    open_slots: int
    prize_pool_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TournamentEntry(TypedDict):
    id: str
    tournament_id: str
    member_id: str
    entry_fee_cents: int
    handicap_spot: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProShopProduct(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_price_cents: int
    stock_qty: int
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    member_id: str
    product_id: Optional[str]
    table_id: Optional[str]
    service_type: str
    quote_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    host_member_id: str
    table_count: int
    start_at: str
    end_at: str
    quote_cents: int
    deposit_cents: int
    deposit_paid_cents: int
    booking_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int
