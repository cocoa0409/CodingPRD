"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource model described in the Community Theater Subscription PRD.
Every primary resource carries id, created_at, updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum (PRD §2.1 — exactly four roles, spelled precisely)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SEASON_ADMIN = "SeasonAdmin"
    BOX_OFFICE_AGENT = "BoxOfficeAgent"
    PATRON = "Patron"
    ARTISTIC_DIRECTOR = "ArtisticDirector"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class SeasonStatus(str, Enum):
    PLANNING = "PLANNING"
    RENEWAL_OPEN = "RENEWAL_OPEN"
    ON_SALE = "ON_SALE"
    CLOSED = "CLOSED"


class ProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"


class PerformanceStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ON_SALE = "ON_SALE"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class SubscriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    RENEWED = "RENEWED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class SubscriptionSeatStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RENEWAL_OFFERED = "RENEWAL_OFFERED"
    RELEASED = "RELEASED"


class TicketPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class TicketFulfillmentStatus(str, Enum):
    HELD = "HELD"
    ISSUED = "ISSUED"
    COLLECTED = "COLLECTED"
    EXCHANGED = "EXCHANGED"
    VOID = "VOID"


class DonationStatus(str, Enum):
    PLEDGED = "PLEDGED"
    FULFILLED = "FULFILLED"
    REFUNDED = "REFUNDED"


class ExchangeStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"


class AuditionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AUDITIONED = "AUDITIONED"
    CALLBACK = "CALLBACK"
    CAST = "CAST"
    DECLINED = "DECLINED"


class DonorLevel(str, Enum):
    NONE = "NONE"
    FRIEND = "FRIEND"
    PATRON = "PATRON"
    BENEFACTOR = "BENEFACTOR"


class PriceTier(str, Enum):
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    VALUE = "VALUE"


class AccessibilityService(str, Enum):
    NONE = "NONE"
    ASL = "ASL"
    AUDIO_DESCRIPTION = "AUDIO_DESCRIPTION"
    OPEN_CAPTION = "OPEN_CAPTION"


class ExchangeMode(str, Enum):
    FLEX_PASS = "FLEX_PASS"
    PAID_EXCHANGE = "PAID_EXCHANGE"


class TicketOrigin(str, Enum):
    SINGLE = "SINGLE"
    SUBSCRIPTION = "SUBSCRIPTION"


# --------------------------------------------------------------------------
# Entity TypedDicts — every primary resource carries the common fields
# (id, created_at, updated_at, version) per PRD §2.4.
# --------------------------------------------------------------------------
class Season(TypedDict):
    id: str
    name: str
    status: str
    renewal_window_opens_at: str
    renewal_window_closes_at: str
    base_subscription_fee_cents: int
    loyalty_renewal_discount_pct: float
    released_seat_count: int
    created_at: str
    updated_at: str
    version: int


class Production(TypedDict):
    id: str
    season_id: str
    title: str
    accessibility_offered: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    total_seat_count: int
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict):
    id: str
    venue_id: str
    section: str
    row_label: str
    seat_number: int
    price_tier: str
    is_accessible: bool
    naming_status: str
    named_plaque_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Performance(TypedDict):
    id: str
    production_id: str
    venue_id: str
    starts_at: str
    on_sale_at: str
    will_call_cutoff_minutes: int
    status: str
    demand_multiplier: float
    capacity: int
    held_seat_count: int
    sold_seat_count: int
    available_seat_count: int
    gross_sales_cents: int
    created_at: str
    updated_at: str
    version: int


class Patron(TypedDict):
    id: str
    email: str
    full_name: str
    donor_level: str
    lifetime_donation_cents: int
    account_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    season_id: str
    patron_id: str
    prior_subscription_id: Optional[str]
    status: str
    is_renewal: bool
    seat_count: int
    total_price_cents: int
    created_at: str
    updated_at: str
    version: int


class SubscriptionSeat(TypedDict):
    id: str
    subscription_id: str
    seat_id: str
    status: str
    per_seat_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    performance_id: str
    seat_id: str
    patron_id: str
    subscription_id: Optional[str]
    origin: str
    payment_status: str
    fulfillment_status: str
    price_cents: int
    hold_expires_at: str
    accessibility_service: str
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    patron_id: str
    seat_id: Optional[str]
    amount_cents: int
    plaque_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Exchange(TypedDict):
    id: str
    original_ticket_id: str
    target_performance_id: str
    target_seat_id: str
    mode: str
    status: str
    fee_cents: int
    price_delta_cents: int
    new_ticket_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Audition(TypedDict):
    id: str
    production_id: str
    applicant_name: str
    role_applied_for: str
    status: str
    cast_role: Optional[str]
    is_volunteer: bool
    created_at: str
    updated_at: str
    version: int
