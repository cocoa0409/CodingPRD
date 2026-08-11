"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the four common server-managed properties described in
PRD §2.4 (id, created_at, updated_at, version) in addition to its domain fields.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    COACH = "Coach"
    RANGE_OFFICER = "RangeOfficer"
    SHOP_CLERK = "ShopClerk"
    LEAGUE_DIRECTOR = "LeagueDirector"
    ADMIN = "Admin"


class MemberTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    ELITE = "ELITE"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class WaiverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LaneType(str, Enum):
    INDOOR = "INDOOR"
    OUTDOOR = "OUTDOOR"


class BookingType(str, Enum):
    WALK_IN = "WALK_IN"
    RESERVATION = "RESERVATION"


class SessionStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, Enum):
    WALLET = "WALLET"
    PUNCH_CARD = "PUNCH_CARD"


class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class PunchCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class RentalItemType(str, Enum):
    BOW = "BOW"
    ARROW_SET = "ARROW_SET"
    ARMGUARD = "ARMGUARD"
    RELEASE = "RELEASE"


class RentalItemStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"


class RentalAgreementStatus(str, Enum):
    OPEN = "OPEN"
    RETURNED = "RETURNED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class ReturnedCondition(str, Enum):
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"


class CoachStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Discipline(str, Enum):
    RECURVE = "RECURVE"
    COMPOUND = "COMPOUND"
    TRADITIONAL = "TRADITIONAL"


class LessonStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COUNTERED = "COUNTERED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LeagueStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LeagueEntryStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class RefundStatus(str, Enum):
    NONE = "NONE"
    REFUNDED = "REFUNDED"


class ScoreCardStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    LOCKED = "LOCKED"


class RepairOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    QUOTED = "QUOTED"
    IN_REPAIR = "IN_REPAIR"
    DECLINED = "DECLINED"
    READY = "READY"
    PICKED_UP = "PICKED_UP"


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    tier: str
    guardian_id: Optional[str]
    is_minor: bool
    status: str
    safety_strikes: int
    wallet_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict, total=False):
    id: str
    member_id: str
    signed_by_member_id: str
    signed_at: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lane(TypedDict, total=False):
    id: str
    name: str
    lane_type: str
    max_archers: int
    created_at: str
    updated_at: str
    version: int


class RangeSession(TypedDict, total=False):
    id: str
    lane_id: str
    created_by_member_id: str
    booking_type: str
    start_at: str
    end_at: str
    booked_minutes: int
    session_status: str
    payment_status: str
    quoted_charge_cents: int
    final_charge_cents: Optional[int]
    cancellation_refund_cents: Optional[int]
    checked_in_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SessionParticipant(TypedDict, total=False):
    id: str
    session_id: str
    member_id: str
    payment_method: str
    punch_card_id: Optional[str]
    quoted_fee_cents: int
    final_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchCard(TypedDict, total=False):
    id: str
    member_id: str
    punches_total: int
    punches_used: int
    punches_remaining: int
    price_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalItem(TypedDict, total=False):
    id: str
    name: str
    item_type: str
    daily_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict, total=False):
    id: str
    rental_item_id: str
    member_id: str
    session_id: Optional[str]
    draw_length_in: float
    draw_weight_lb: int
    checked_out_at: str
    due_date: str
    returned_at: Optional[str]
    returned_condition: Optional[str]
    damage_fee_cents: int
    status: str
    settlement_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict, total=False):
    id: str
    full_name: str
    disciplines: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lesson(TypedDict, total=False):
    id: str
    coach_id: str
    member_id: str
    discipline: str
    proposed_start_at: str
    duration_minutes: int
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class League(TypedDict, total=False):
    id: str
    name: str
    entry_fee_cents: int
    max_entries: int
    status: str
    gross_entry_fees_cents: int
    range_share_cents: int
    prize_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class LeagueEntry(TypedDict, total=False):
    id: str
    league_id: str
    member_id: str
    fee_paid_cents: int
    status: str
    refund_status: str
    created_at: str
    updated_at: str
    version: int


class ScoreCard(TypedDict, total=False):
    id: str
    league_entry_id: str
    ends: List[List[int]]
    x_hits: int
    total_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShopProduct(TypedDict, total=False):
    id: str
    name: str
    sku: str
    unit_price_cents: int
    stock_quantity: int
    initial_stock: int
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict, total=False):
    id: str
    member_id: Optional[str]
    items: List[Dict[str, Any]]
    line_gross_cents: List[int]
    subtotal_cents: int
    volume_discount_cents: int
    tax_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict, total=False):
    id: str
    member_id: str
    item_description: str
    status: str
    parts_reserved: List[Dict[str, Any]]
    labor_minutes: Optional[int]
    promised_hours: Optional[int]
    parts_total_cents: Optional[int]
    labor_total_cents: Optional[int]
    quote_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
